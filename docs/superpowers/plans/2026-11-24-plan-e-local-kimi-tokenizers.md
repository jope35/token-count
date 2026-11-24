# Plan E: local Kimi tokenizers (kimi_local strategy) — Implementation Plan

Add offline counting for the four Kimi models already in the API registry
(`kimi-k3.1-pro`, `kimi-k3`, `kimi-k2.7-code`, `kimi-k2.6`) by vendoring their
tiktoken tokenizer files and counting locally with `tiktoken` (already a
dependency), instead of the Moonshot API.

All technical facts below were verified on 2026-11-24 by downloading the files
from Hugging Face and running tiktoken 0.14.0 locally (all asserts passed).

## Global Constraints

- The four repos ship a **byte-identical** `tiktoken.model`
  (sha256 `b6c497a7469b33ced9c38afb1ad6e47f03f5e5dc05f15930799210ec050c5103`,
  2,795,286 bytes, 163,584 BPE ranks → `n_vocab` 163,840 = 163,584 + 256 reserved).
- `pat_str` in each repo's `tokenization_kimi.py` is **identical** across all four:
  ```python
  PAT_STR = "|".join([
      r"""[\p{Han}]+""",
      r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
      r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
      r"""\p{N}{1,3}""",
      r""" ?[^\s\p{L}\p{N}]+[\r\n]*""",
      r"""\s*[\r\n]+""",
      r"""\s+(?!\S)""",
      r"""\s+""",
  ])
  ```
- Special tokens are built as the **full reserved range**
  `[num_base, num_base + 256)`, name taken from `tokenizer_config.json`'s
  `added_tokens_decoder` when present, else `<|reserved_token_{i}|>`
  (exactly what `tokenization_kimi.py` does — do NOT build only from
  `added_tokens_decoder`; K3's `<|open|> <|close|> <|sep|>` are flagged
  `special: false` in the config but are still tiktoken-special).
- Per-model special tokens differ (verified): K3/K3.1-Pro have 16 added tokens
  (`<|end_of_msg|>`, media tokens, `<osagent_mode>`, …); K2.6/K2.7-Code have 23
  (the `<|im_*|>` chat tokens + media). Plain-text token IDs are identical across
  all four models.
- Encode with `allowed_special="all"` (parity with `hf_local`, whose added tokens
  are matched even with `add_special_tokens=False`). Chunk input at 400,000 chars
  per `encode()` call (tiktoken panics above that; all four repos' wrappers do this).
- Repo conventions: fetch script stays stdlib-only; minimal diffs; follow existing
  patterns (`hf_local` loads its tokenizer per call — no cache needed);
  tests run with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.
- Registry model ids must stay globally unique (test pins this), so the local
  rows use the API id plus a `-local` suffix (e.g. `kimi-k3-local`).
- Pinned HF revisions (sha of `main` on 2026-11-24):
  - `moonshotai/Kimi-K3.1-Pro` @ `d9e99b0792a5e93b78ea9bea62a68167e36ddd9e`
  - `moonshotai/Kimi-K3` @ `c7945ea0e737dcaddd22c68ddb7639b1407c081c`
  - `moonshotai/Kimi-K2.7-Code` @ `74797c9c62378b951a1f6fcf5c4631024e9b8bef`
  - `moonshotai/Kimi-K2.6` @ `7eb5002f6aadc958aed6a9177b7ed26bb94011bb`

## Task 1: Vendor the Kimi tokenizer files via `scripts/fetch_tokenizers.py`

- Extend `scripts/fetch_tokenizers.py` (stdlib only) with a Kimi table holding
  `(local_name, repo, pinned_sha)` for the four repos above and a fixed file list
  `["tiktoken.model", "tokenizer_config.json"]`. Each entry downloads both files
  from `https://huggingface.co/{repo}/resolve/{sha}/{file}` into a per-model
  directory `tokenizers/<local_name>/` (e.g. `tokenizers/kimi-k3/tiktoken.model`).
  Keep the existing `TOKENIZERS` 4-tuple path untouched. Validate JSON only for
  `.json` files (`tiktoken.model` is base64 BPE, not JSON). Print path, size,
  sha256 per file like the existing code.
- Run `.venv/bin/python scripts/fetch_tokenizers.py` from the repo root and commit
  the new `tokenizers/kimi-*/` files. Verify the four `tiktoken.model` files have
  identical sha256 `b6c497a7…` (they are the same file upstream).

## Task 2: `kimi_local` strategy in the counter layer

- New module `src/tokencount/kimi.py` with `PAT_STR` (above, verbatim) and
  `load_encoding(tokenizer_dir: str) -> tiktoken.Encoding` that reads
  `tokenizer_dir/tiktoken.model` via `tiktoken.load.load_tiktoken_bpe`, reads
  `tokenizer_dir/tokenizer_config.json`, builds `special_tokens` over the full
  reserved range as specified above, and returns the `Encoding`. Add
  `count(enc, text)` helper that chunks text at 400,000 chars and encodes each
  chunk with `allowed_special="all"`, returning the total id count.
- `src/tokencount/counters.py`: add `LOCAL_STRATEGIES = {"hf_local", "kimi_local"}`
  next to `STRATEGY_KEY_ENV`; in `count_tokens`, add a `kimi_local` branch mirroring
  the `hf_local` one: require `tokenizer_file` (else `ValueError("kimi_local requires
  tokenizer_file")`), then `return kimi.count(kimi.load_encoding(tokenizer_file), text)`.
  `kimi_local` needs no key and no baseline (like `hf_local`).
- `src/tokencount/run.py`: replace both `strategy == "hf_local"` checks (the
  sequential-vs-pool choice in `run_worker` and the family split in
  `split_families`) with `strategy in counters.LOCAL_STRATEGIES` (import counters;
  check how run.py already imports it and follow that).

## Task 3: Registry rows for the four local Kimi models

- In `src/tokencount/models.py`, append to the local `REGISTRY += [...]` block four
  `Model` rows, following the existing local-row style:
  `provider="kimi"`, `family="kimi_local"`, `strategy="kimi_local"`, `key_env=None`,
  `tokenizer_file="tokenizers/kimi-<id>"` (the directory from Task 1), with model ids
  `kimi-k3.1-pro-local`, `kimi-k3-local`, `kimi-k2.7-code-local`, `kimi-k2.6-local`.

## Task 4: Test updates and full suite green

- `tests/test_models.py`: registry size pin `len(REGISTRY) == 23` → `27`; add
  `"kimi_local"` to `KNOWN_STRATEGIES`; extend the local-families test with
  `models_for_family("kimi_local")` == the four `-local` ids, and for
  `kimi_local` rows assert `key_env is None` and `os.path.isdir(tokenizer_file)`.
- `tests/test_counters.py`: add `EXPECTED_KIMI_LOCAL = {"tokenizers/kimi-k3": N, …}`
  pinned counts for `KNOWN_STRING` (get each integer by running the Task 2 loader on
  `KNOWN_STRING`; expect the same value for all four since plain-text ids are
  identical). Add tests mirroring the hf_local ones: `kimi_local` without
  `tokenizer_file` raises `ValueError`; known vectors match; a special token from
  the model's own config (e.g. `<|im_end|>` for kimi-k2.6, `<|end_of_msg|>` for
  kimi-k3) encodes to exactly its config id, and a special token from the *other*
  line (e.g. `<|end_of_msg|>` on kimi-k2.6) encodes to more than one id.
- `tests/test_run.py`: update the `split_families` expectation so `kimi_local` lands
  in the local set alongside `deepseek`, `mistral`, `glm_local`.
- Run the full suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` —
  all green, output pristine.

## Task 5: README + end-to-end verification

- `README.md`: update the local-model mentions (the "five DeepSeek and Mistral
  models counted offline" sentence and the "Add a local model" section) to include
  the four local Kimi models and note they are vendored as
  `tokenizers/<name>/{tiktoken.model,tokenizer_config.json}` and counted with
  tiktoken via the `kimi_local` strategy.
- End-to-end: `PYTHONPATH=src .venv/bin/python -m tokencount --family kimi_local
  --results-csv /tmp/kimi-e2e.csv` (scratch CSV — do NOT touch `results/results.csv`),
  confirm rows appear for the four `-local` models, then run the full test suite
  once more.
