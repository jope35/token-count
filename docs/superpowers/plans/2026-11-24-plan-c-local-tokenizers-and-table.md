# Plan C: local tokenizers and table — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vendor the five Hugging Face tokenizer files, add the `hf_local` counting strategy plus the five local model rows, dispatch the deepseek and mistral families from the orchestrator, and render `results/table.md` from `results/results.csv`.

**Architecture:** DeepSeek and Mistral expose no token-counting endpoint, so their rows are counted offline with tokenizer files vendored from Hugging Face into `tokenizers/` and loaded with the `tokenizers` library inside `.venv-deepseek` and `.venv-mistral`. The base-env orchestrator runs one subprocess per family, the local families included, and after all families finish it calls `table.write_table()`, which pivots the CSV into a Markdown table with one row per registry model and one column per corpus file type plus a Total column.

**Tech Stack:** Python, stdlib `unittest` for tests, `tokenizers` in `.venv-deepseek`/`.venv-mistral`, `tiktoken` in `.venv-api` (OpenAI cross-check only), `httpx` + `secretspec>=0.21,<0.22` in base `.venv`, stdlib `urllib` for plain HTTPS in the fetch script. No `huggingface-hub` at run time.

**Spec:** docs/superpowers/specs/2026-11-23-token-count-table-design.md

**Depends on:** Plan A owns `src/tokencount/corpus.py`. Plan B owns `src/tokencount/models.py` (the 18 API rows), `src/tokencount/counters.py` (the API strategies and the `count_tokens`/`baseline_tokens` dispatch), and `src/tokencount/run.py` (orchestrator, worker, CSV append, `route_env(family)`, `family_env(family, secrets)`, and the marked `render_results()` stub hook). This plan appends to those files. It does not change plan B's API strategy functions.

## Global Constraints

- Shared interface contract (exact names and signatures, agreed 2026-11-24):
  - `corpus.py` (plan A): `@dataclass CorpusEntry(file_type, name, url, repo, sha, path)`; `load_entries() -> list[CorpusEntry]`; `@dataclass Sample(path, file_type, name, sha256, chars, text)`; `fetch_corpus(entries, dest_dir="samples", fresh=False) -> list[Sample]`.
  - `models.py`: `@dataclass Model(provider, model, family, strategy, key_env, tokenizer_file)`; `REGISTRY: list[Model]`; `models_for_family(family) -> list[Model]`. Plan B filled the API families; this plan appends the five `hf_local` rows.
  - `counters.py`: `count_tokens(strategy, model_id, text, key=None, tokenizer_file=None) -> int`; `baseline_tokens(strategy, model_id, key) -> int`. This plan adds the `hf_local` branch.
  - `run.py`: `main(argv=None)`. Orchestrator dispatches `<route_env>/bin/python -m tokencount --family <family>` per family with only that family's key in env, then calls the table hook. Worker appends CSV rows. This plan extends the family list with `deepseek` (`.venv-deepseek`) and `mistral` (`.venv-mistral`) and implements the render hook.
  - `table.py` (this plan creates it): `pivot(rows) -> ...`; `render_markdown(pivot) -> str`; `write_table(csv_path="results/results.csv", out_path="results/table.md")` writes the file and prints to stdout.
- CSV columns: `timestamp,provider,model,strategy,file,file_type,sha256,chars,tokens,note`. Dedup key: `(model, strategy, file, sha256)`. Notes: `error: <message>`, `n/a`, `missing key <ENV>`. The table renders those as `error`, `n/a`, `key`.
- Table shape: rows = models (registry order), columns = file types from the corpus plus `Total`. A cell is the sum of numeric tokens for that model and file type, or the note. `Total` sums numeric cells only.
- Run command: `PYTHONPATH=src .venv/bin/python -m tokencount`. Tests: `.venv/bin/python -m unittest tests.test_table`, `.venv-deepseek/bin/python -m unittest tests.test_counters`, `.venv-api/bin/python -m unittest tests.test_counters` (the same module; local-vector tests skip when `tokenizers` is absent).
- Tokenizer files are vendored and committed. The fetch script uses plain HTTPS and runs once when the registry changes. Local strategies need no key, so a partial run works offline.
- `hf_local` encodes the raw text directly. No baseline subtraction for this strategy.

## Review Focus

1. Wrong Hugging Face repo or wrong file vendored (for example `tokenizer.json` instead of `tekken.json` for Mistral). Pinned by the verification commands and pinned revision shas in Task 1, and by the known-vector test per vendored file in Task 3, because a swapped file produces a different token count for the fixed string.
2. `hf_local` accidentally wrapped or baseline-subtracted like a message API. Pinned by the Task 3 test that pins the raw `len(ids)` count for a fixed string, with no baseline term.
3. `Total` column sums error, n/a, or key cells. Pinned by the Task 5 pivot test that includes note rows and asserts Total equals the sum of numeric cells only.
4. A missing key renders as a blank or zero cell instead of `key`. Pinned by the Task 5 render test and by the Task 6 end-to-end run, where API rows must carry `missing key <ENV>` and render `key`.
5. Reruns append duplicate rows, or `--fresh` silently skips work. Pinned by the Task 5 dedup-key test and by the Task 6 rerun (zero new rows) and `--fresh` (full recount) checks.

## Task 1: Vendor the tokenizer files

**Files:**
- Create: `scripts/fetch_tokenizers.py`
- Create: `tokenizers/deepseek-flash.json`, `tokenizers/deepseek-v4-pro.json`, `tokenizers/mistral-large-4.json`, `tokenizers/mistral-small-2603.json`, `tokenizers/mistral-medium-3-5.json`

**Interfaces:**
- Consumes: the model names from the spec's registry section: deepseek-flash (DeepSeek-V4.1-Flash-1017), deepseek-v4-pro (DeepSeek-V4-Pro-0813), mistral-large-4, mistral-small-2603, mistral-medium-3-5.
- Produces: the five committed files above. `models.py` in Task 2 points at them as `tokenizers/<provider>-<model>.json`.

Verified against the live Hugging Face API on 2026-11-24 (record these exact values in the script):

| local name | HF repo | revision sha | HF file | vendored as |
|---|---|---|---|---|
| deepseek-flash | deepseek-ai/DeepSeek-V4.1-Flash-1017 | 08c8657f02291e11b6f6b63e0e16014f8e748518 | tokenizer.json | tokenizers/deepseek-flash.json |
| deepseek-v4-pro | deepseek-ai/DeepSeek-V4-Pro-0813 | 72e1d3230f6c080a530b0a1d46f8eb4602340597 | tokenizer.json | tokenizers/deepseek-v4-pro.json |
| mistral-large-4 | mistralai/Mistral-Large-4-1T-A52B | af26e7869af601441d5cdf75a1272469ddc3d059 | tekken.json | tokenizers/mistral-large-4.json |
| mistral-small-2603 | mistralai/Mistral-Small-4-119B-2603 | a11f36bebf709121056b1dbcc943d1c6afbe494d | tekken.json | tokenizers/mistral-small-2603.json |
| mistral-medium-3-5 | mistralai/Mistral-Medium-3.5-128B | 22b2b868a15677cfa6061277ed2f653d1349a9ab | tekken.json | tokenizers/mistral-medium-3-5.json |

Note: mistral-small-2603 and mistral-medium-3-5 currently ship the same `tekken.json` blob (same LFS oid). That is expected, not a download bug. Each still gets its own vendored file. Per the spec, Mistral uses `tekken.json`, DeepSeek uses `tokenizer.json`.

- [ ] **Step 1:** Verify each repo id and revision sha once via the HF API, from the repo root:
  `curl -sf https://huggingface.co/api/models/deepseek-ai/DeepSeek-V4.1-Flash-1017 | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['sha'])"`
  Expected: `08c8657f02291e11b6f6b63e0e16014f8e748518`. Repeat for the other four repos and match the table above. Also list each repo's files: `curl -sf https://huggingface.co/api/models/<repo>/tree/main` and make sure that the HF file in the table exists in the listing.
- [ ] **Step 2:** Write `scripts/fetch_tokenizers.py`. It holds the table above as data: local name, repo, locked revision sha, HF file name. For each entry it downloads `https://huggingface.co/<repo>/resolve/<sha>/<hf_file>` with stdlib `urllib.request` into `tokenizers/<local-name>.json` and prints the local path, byte count, and sha256 of the downloaded bytes. No `huggingface-hub`, no third-party packages.
- [ ] **Step 3:** Run it: `.venv/bin/python scripts/fetch_tokenizers.py`. Expected: five lines, five files created. Make sure that each downloaded file is valid JSON: `.venv/bin/python -c "import json,glob; [json.load(open(p)) for p in glob.glob('tokenizers/*.json')]; print('ok')"` prints `ok`.
- [ ] **Step 4:** Make sure that a pinned download URL resolves: `curl -sIL https://huggingface.co/mistralai/Mistral-Large-4-1T-A52B/resolve/af26e7869af601441d5cdf75a1272469ddc3d059/tekken.json` returns HTTP 200 after redirects.
- [ ] **Step 5:** Commit: `git add scripts/fetch_tokenizers.py tokenizers/ && git commit -m "feat: vendor deepseek and mistral tokenizer files from hugging face"`

## Task 2: Registry rows for the five local models

**Files:**
- Modify: `src/tokencount/models.py` (plan B's file; append rows)
- Test: `tests/test_models.py` (plan B's module; extend the registry integrity test there)

**Interfaces:**
- Consumes: `Model(provider, model, family, strategy, key_env, tokenizer_file)`, `REGISTRY`, `models_for_family(family)` from plan B's `models.py`; the vendored files from Task 1.
- Produces: five appended rows in `REGISTRY`, appended after plan B's API rows:
  - `Model(provider="deepseek", model="deepseek-flash", family="deepseek", strategy="hf_local", key_env=None, tokenizer_file="tokenizers/deepseek-flash.json")`
  - `Model(provider="deepseek", model="deepseek-v4-pro", family="deepseek", strategy="hf_local", key_env=None, tokenizer_file="tokenizers/deepseek-v4-pro.json")`
  - `Model(provider="mistral", model="mistral-large-4", family="mistral", strategy="hf_local", key_env=None, tokenizer_file="tokenizers/mistral-large-4.json")`
  - `Model(provider="mistral", model="mistral-small-2603", family="mistral", strategy="hf_local", key_env=None, tokenizer_file="tokenizers/mistral-small-2603.json")`
  - `Model(provider="mistral", model="mistral-medium-3-5", family="mistral", strategy="hf_local", key_env=None, tokenizer_file="tokenizers/mistral-medium-3-5.json")`

- [ ] **Step 1:** Write the failing test in `tests/test_models.py` (runs in base `.venv` and in the local envs): extend plan B's registry integrity test to assert `len(REGISTRY) == 23` (plan B pins 18 API rows; this plan adds 5), `len(models_for_family("deepseek")) == 2`, `len(models_for_family("mistral")) == 3`, and that every `hf_local` row has `key_env is None` and an existing `tokenizer_file` under `tokenizers/`.
- [ ] **Step 2:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_models -v`. Expected: FAIL, because the five rows are missing and the count is not 23.
- [ ] **Step 3:** Append the five `Model(...)` rows to `REGISTRY` in `src/tokencount/models.py`, using keyword arguments exactly as above.
- [ ] **Step 4:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_models -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git add src/tokencount/models.py tests/test_models.py && git commit -m "feat: add hf_local registry rows for deepseek and mistral"`

## Task 3: The hf_local counting strategy and its tests

**Files:**
- Modify: `src/tokencount/counters.py` (plan B's dispatch)
- Test: `tests/test_counters.py` (add the local vectors and the tiktoken cross-check)

**Interfaces:**
- Consumes: `count_tokens(strategy, model_id, text, key=None, tokenizer_file=None) -> int` and `baseline_tokens(strategy, model_id, key) -> int` from plan B. The dispatch already routes by `strategy`; this task adds the `hf_local` branch and does not touch the API branches or the baseline subtraction.
- Produces: for `strategy == "hf_local"`, `count_tokens` loads the vendored file named by `tokenizer_file` with `tokenizers.Tokenizer.from_file`, encodes `text`, and returns `len(encoding.ids)`. No key, no baseline, no chat template. `baseline_tokens` is never called for `hf_local`.

- [ ] **Step 1:** Add the failing tests to `tests/test_counters.py`:
  - One fixed string, shared by all tests: `KNOWN_STRING = "The quick brown fox jumps over the lazy dog. 0123456789"`.
  - A dict `EXPECTED_HF_LOCAL = {"tokenizers/deepseek-flash.json": <n1>, "tokenizers/deepseek-v4-pro.json": <n2>, "tokenizers/mistral-large-4.json": <n3>, "tokenizers/mistral-small-2603.json": <n4>, "tokenizers/mistral-medium-3-5.json": <n5>}` with placeholder ints, and `test_hf_local_known_vectors` asserting `count_tokens("hf_local", "x", KNOWN_STRING, tokenizer_file=path) == expected` for each path. Guard the import of `tokenizers` with `unittest.skipUnless` so the module still runs in `.venv-api`.
  - `test_hf_local_no_baseline`: assert that the `hf_local` branch returns exactly `len(ids)` and that `baseline_tokens` is not involved, by pinning the same fixed-string count twice: once via `count_tokens(...)` and once via a direct `Tokenizer.from_file(path).encode(KNOWN_STRING)` in the test, and asserting equality.
  - `test_openai_tiktoken_cross_check`: pin `KNOWN_STRING` against `tiktoken` with the same encoding name that plan B's `openai_api` counter uses (read it from `counters.py`), asserting one exact integer. Guard with `skipUnless` on tiktoken so the module still runs in `.venv-deepseek`.
- [ ] **Step 2:** Run `.venv-deepseek/bin/python -m unittest tests.test_counters -v`. Expected: the local vector tests FAIL with the placeholder ints.
- [ ] **Step 3:** Implement the branch in `src/tokencount/counters.py`: in `count_tokens`, if `strategy == "hf_local"`, require `tokenizer_file`, load `Tokenizer.from_file(tokenizer_file)`, and return `len(tok.encode(text).ids)`.
- [ ] **Step 4:** Fill in the real expected ints: run `.venv-deepseek/bin/python -c "from tokenizers import Tokenizer; print(len(Tokenizer.from_file('tokenizers/deepseek-flash.json').encode('The quick brown fox jumps over the lazy dog. 0123456789').ids))"` per file and put each printed integer into `EXPECTED_HF_LOCAL`. Run `.venv/bin/python -c` with tiktoken absent is fine; get the tiktoken int in `.venv-api`: `.venv-api/bin/python -c "import tiktoken; e=tiktoken.get_encoding('<encoding from counters.py>'); print(len(e.encode('The quick brown fox jumps over the lazy dog. 0123456789')))"`.
- [ ] **Step 5:** Run all three: `.venv-deepseek/bin/python -m unittest tests.test_counters -v`, `.venv-mistral/bin/python -m unittest tests.test_counters -v`, `.venv-api/bin/python -m unittest tests.test_counters -v`. Expected: PASS in all three (skipped where the library is absent).
- [ ] **Step 6:** Commit: `git add src/tokencount/counters.py tests/test_counters.py && git commit -m "feat: add hf_local strategy with pinned known vectors"`

## Task 4: Local-family dispatch and the render hook in the orchestrator

**Files:**
- Modify: `src/tokencount/run.py` (plan B's orchestrator; only the `render_results()` stub body changes)
- Test: `tests/test_run.py` (plan B's module; extend it with the local-route and hook tests, since they run in base `.venv`)

**Interfaces:**
- Consumes: plan B's `main(argv=None)`, `route_env(family) -> str` (already returns `.venv-api` for the five API families and `.venv-<family>` otherwise, so the local families need no route change), `family_env(family, secrets) -> dict`, its per-family dispatch of `<route_env(family)>/bin/python -m tokencount --family <family>` iterating the unique families in `REGISTRY`, its CSV append with the schema in Global Constraints, and the marked `render_results()` stub (`# PLAN C HOOK`). Also consumes `models_for_family` from Task 2 and `table.write_table()` from Task 5.
- Produces: the orchestrator dispatches seven families: `openai`, `anthropic`, `google`, `glm`, `kimi` in `.venv-api` (plan B), plus `deepseek` in `.venv-deepseek` and `mistral` in `.venv-mistral` (this task, via the registry rows and the existing `route_env` fallback). After all families finish, `render_results()` calls `table.write_table()`.

- [ ] **Step 1:** Append the failing tests to `tests/test_run.py`:
  - `test_local_families_route_to_their_envs`: assert `run.route_env("deepseek") == ".venv-deepseek"` and `run.route_env("mistral") == ".venv-mistral"`, and that the five API families still return `.venv-api`.
  - `test_local_family_gets_no_key`: call `run.family_env("deepseek", ALL_SECRETS)` with all five API keys present and assert the returned env is exactly `{"PYTHONPATH": "src"}` (no key leaks into a local family).
  - `test_render_results_calls_write_table`: monkeypatch `table.write_table` with a recorder, call `run.render_results()`, and assert it was called once.
- [ ] **Step 2:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`. Expected: FAIL on `test_render_results_calls_write_table` (the stub does not call `table.write_table` yet); the route tests pass already because `route_env` falls back to `.venv-<family>`.
- [ ] **Step 3:** In `src/tokencount/run.py`, replace the body of the marked `render_results()` stub with `from tokencount import table` at module top and `def render_results() -> None: table.write_table()`. Make no other change: the dispatch loop already iterates the unique families in `REGISTRY`, and `route_env`/`family_env` already handle the local families.
- [ ] **Step 4:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git add src/tokencount/run.py tests/test_run.py && git commit -m "feat: render results table after all families finish"`

## Task 5: The table pivot and Markdown render

**Files:**
- Create: `src/tokencount/table.py`
- Create: `tests/test_table.py` (plan B owns `test_models`/`test_counters`/`test_run`; this plan adds `test_table`)

**Interfaces:**
- Consumes: CSV rows as `dict`s with the columns in Global Constraints (plan B's worker writes them); `REGISTRY` from `models.py` for the row order and model list; `load_entries()` from plan A's `corpus.py` for the column (file type) order. `run.py` from Task 4 calls `write_table()`.
- Produces:
  - `dedup_key(row) -> tuple[str, str, str, str]` returning `(row["model"], row["strategy"], row["file"], row["sha256"])`.
  - `pivot(rows, models=None, file_types=None)` returning `(file_types, cells)` where `cells[model][file_type]` is an `int` (sum of numeric `tokens`) or a note `str`. Default `models` is `[m.model for m in REGISTRY]`; default `file_types` is the unique file types from `load_entries()` in first-seen order.
  - `render_markdown(pivot) -> str` where `pivot` is the tuple from `pivot`. Header row `| model | <file_type> ... | Total |`, then a `|---|` separator, then one row per model. Note cells render as `error` (note starts with `error:`), `key` (note starts with `missing key`), `n/a` (note is `n/a`). If several notes hit one cell, precedence is `error`, then `missing key`, then `n/a`. A model/file-type pair with no CSV row renders `n/a`. `Total` is the sum of the numeric cells of the row and renders `0` when there are none.
  - `write_table(csv_path="results/results.csv", out_path="results/table.md") -> str`: reads the CSV with `csv.DictReader`, calls `pivot(rows)`, `render_markdown(...)`, writes the result to `out_path`, prints it to stdout, and returns it.

- [ ] **Step 1:** Write the failing tests in `tests/test_table.py`, using small in-memory row dicts (no real CSV):
  - `test_pivot_sums_numeric_and_carries_notes`: rows for one model with two files of type `python` (tokens 10 and 5), one `error: boom` row for type `json`, one `n/a` row for `html`, one `missing key OPENAI_API_KEY` row for `text`. Pass explicit `models` and `file_types`. Assert `cells[model]["python"] == 15`, the note cells carry the note strings, and a pair with no rows is `n/a`.
  - `test_render_markdown_shape_and_total`: from the same pivot assert the header is `| model | python | json | html | text | Total |`, there is one row per model, the `python` cell renders `15`, the note cells render `error`, `n/a`, `key`, and `Total` equals the sum of numeric cells only (not the notes).
  - `test_dedup_key`: two rows that differ only in `timestamp` and `tokens` produce the same `dedup_key`; a row with a different `sha256` produces a different key.
  - `test_write_table_roundtrip`: write a small CSV to a temp dir, call `write_table(csv_path=tmp_csv, out_path=tmp_md)`, assert the returned string equals the file content and that the file content has the header shape above.
- [ ] **Step 2:** Run `.venv/bin/python -m unittest tests.test_table -v`. Expected: FAIL with `table` not importable.
- [ ] **Step 3:** Implement `src/tokencount/table.py` with the four functions and signatures above, stdlib only (`csv`, `os`, and the two imports from sibling modules).
- [ ] **Step 4:** Run `.venv/bin/python -m unittest tests.test_table -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git add src/tokencount/table.py tests/test_table.py && git commit -m "feat: pivot results csv and render markdown table"`

## Task 6: End-to-end offline verification

**Files:**
- Verify only: `results/results.csv`, `results/table.md` (generated and committed per the spec)

**Interfaces:**
- Consumes: everything above. Plan A's envs and corpus must exist; if plan A has not landed yet, this task waits for it.

- [ ] **Step 1:** Run with no keys and no sops on PATH: `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GOOGLE_API_KEY -u Z_AI_API_KEY -u MOONSHOT_API_KEY PATH=/usr/bin:/bin PYTHONPATH=src .venv/bin/python -m tokencount`. Expected: exit code 0. In `results/results.csv` the deepseek and mistral rows have numeric `tokens`, and every API-family row has note `missing key <ENV>` with an empty `tokens`.
- [ ] **Step 2:** Make sure that `results/table.md` was regenerated: it has one row per registry model (23 rows: 18 API + 5 local) and one column per corpus file type plus `Total`. Deepseek and mistral cells are numeric; API cells render `key`.
- [ ] **Step 3:** Rerun the same command. Expected: exit 0 and zero new rows in `results/results.csv` (compare `wc -l` before and after). This is the dedup check: an unchanged corpus adds no rows.
- [ ] **Step 4:** Run with `--fresh`: `PYTHONPATH=src .venv/bin/python -m tokencount --fresh`. Expected: every pair is recounted (row count stays the same set of dedup keys, timestamps update).
- [ ] **Step 5:** Check every Total: `.venv/bin/python - <<'EOF'` script that parses `results/table.md`, and for each row asserts that the Total column equals the sum of the numeric cells in that row. Print `ok`.
- [ ] **Step 6:** Commit the regenerated artifacts: `git add results/ && git commit -m "chore: regenerate results and table from offline run"`

## Handoff

- Plan C delivers: `scripts/fetch_tokenizers.py` plus five committed files in `tokenizers/`; the five `hf_local` rows in `REGISTRY` (23 models total: plan B's 18 API rows + 5 local); the `hf_local` branch in `count_tokens`; the `render_results()` hook implemented as `table.write_table()` in `run.py` (the local-family routes come from plan B's `route_env` fallback, no route change needed); and `src/tokencount/table.py` with `pivot`, `render_markdown`, `write_table`, and `dedup_key`, plus tests in `tests/test_table.py`, `tests/test_models.py`, `tests/test_run.py`, and `tests/test_counters.py`.
- Verified once on 2026-11-24 via `https://huggingface.co/api/models/<repo>`: the five repo ids, revision shas, and tokenizer files listed in Task 1. DeepSeek repos ship `tokenizer.json`; the Mistral repos ship `tekken.json`, which is the file the spec mandates for Mistral. Mistral Small 2603 and Medium 3.5 currently share one `tekken.json` blob; both still get their own vendored copy.
- Out of scope for this plan: the corpus (plan A), the five API strategy functions and the baseline subtraction (plan B), secrets handling (plan A), and `devenv.sh` (plan A).
- Registry count is reconciled with plan B: plan B's `tests/test_models.py` pins 18 API rows (`len(REGISTRY) == 18`); this plan's Task 2 raises the pin to 23. If plan B's count ever changes, update both pins in the same commit.
