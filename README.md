# token-count

This tool counts, for every supported model, how many tokens that model's tokenizer produces for each file in a fixed corpus. It appends one row per (model, file) pair to `results/results.csv` and renders `results/table.md`, a Markdown table with one row per model and one column per file type plus a Total column.

## Quickstart

1. Install [uv](https://docs.astral.sh/uv/) (for example `brew install uv`). uv installs the Python version from `.python-version` (3.14) automatically.
2. Run `uv sync` from the repo root. This creates `.venv` from `pyproject.toml` and the committed `uv.lock`.
3. Run the tool:

   ```
   PYTHONPATH=src .venv/bin/python -m tokencount
   ```

The run downloads the corpus into `samples/` (cached unless `--fresh` is given), counts every (model, file) pair, appends rows to `results/results.csv`, and writes `results/table.md`. Run it again with `--fresh` to re-download the corpus and recount everything. A rerun without `--fresh` adds no new rows for unchanged files.

The run uses two paths. A family is one provider's group of models. The 5 API families run in parallel as separate processes, and each process counts its pairs through a pool of 4 (`API_CONCURRENCY`). The local deepseek and mistral families run one at a time afterwards. Each worker appends rows only to its own `results/pending/<family>.csv` (gitignored); after all workers finish, the orchestrator appends those pending files into `results/results.csv`. tqdm shows a corpus-fetch bar and one bar per family. With `--family <name>` the tool runs a single worker that writes `results/results.csv` directly.

The five DeepSeek and Mistral models and the four local Kimi models are counted offline from the committed tokenizer files in `tokenizers/`, so they need no API key and work without network access once `samples/` is cached. The Kimi models (`kimi-k3.1-pro-local`, `kimi-k3-local`, `kimi-k2.7-code-local`, `kimi-k2.6-local`) are vendored as `tokenizers/<name>/{tiktoken.model,tokenizer_config.json}` and counted with tiktoken via the `kimi_local` strategy. The 18 API models need keys (see below); without a key their table cells render `key` instead of a number.

## Secrets

API keys come from the environment. Either export them (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `Z_AI_API_KEY`, `MOONSHOT_API_KEY`) or copy `.env.example` to `.env` and fill in the values. Keep `.env` local (it is gitignored). Process environment variables win over `.env`. Every key is optional: a missing key is reported per model as `missing key <ENV>`, never an abort.

## Results

`results/results.csv` has one row per (model, file) pair with these columns: `timestamp, provider, model, strategy, file, file_type, sha256, chars, tokens, note`. The dedup key is `(model, strategy, file, sha256)`, so a changed file is recounted automatically on the next run.

`results/table.md` pivots the CSV: rows are models in registry order, columns are the corpus file types (`text, python, javascript, shell, rust, go`) plus `Total`. A cell is the sum of the token counts for that model and file type. A cell renders `key`, `error`, or `n/a` when the CSV rows carry a note (`missing key ...`, `error: ...`, `n/a`). `Total` sums the numeric cells of the row only.

## Tests

Run from the repo root:

```
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests
```

Tests that call a live API skip automatically when the matching key is not set.

## Add a model

Every model is one `Model` row in `REGISTRY` in `src/tokencount/models.py`. Pick one of the two strategies below.

### Add an API model

Use this for models that expose a token-counting HTTP endpoint.

1. Add the model id to the list for its family in `_FAMILIES` in `src/tokencount/models.py`. For a new family, add a new `_FAMILIES` entry with its strategy name, key environment variable, and model list.
2. If the family uses a new strategy, add a counter function in `src/tokencount/counters.py` and register it in `_COUNTERS` and `STRATEGY_KEY_ENV`. `baseline_tokens` handles the wrapper offset; return 0 there for string-input endpoints.
3. Add the key environment variable to `.env.example`.
4. Update the registry size pin (`len(REGISTRY) == 23`) in `tests/test_models.py` and run the tests.

### Add a local model (`hf_local`)

Use this for models without a counting endpoint, such as DeepSeek and Mistral. The tokenizer file is vendored and committed, and counting runs offline.

1. Add one entry (local name, Hugging Face repo, pinned revision sha, file `tokenizer.json`) to the `TOKENIZERS` table in `scripts/fetch_tokenizers.py`, then run `.venv/bin/python scripts/fetch_tokenizers.py` from the repo root.
2. Append a `Model(provider=..., model=..., family=..., strategy="hf_local", key_env=None, tokenizer_file="tokenizers/<name>.json")` row to `REGISTRY` in `src/tokencount/models.py`.
3. Add the pinned count for the known test string to `EXPECTED_HF_LOCAL` in `tests/test_counters.py`. Get the integer with:

   ```
   .venv/bin/python -c "from tokenizers import Tokenizer; print(len(Tokenizer.from_file('tokenizers/<name>.json').encode('The quick brown fox jumps over the lazy dog. 0123456789', add_special_tokens=False).ids))"
   ```

4. Update the registry size pin in `tests/test_models.py` and run the tests.

### Add a local Kimi model (`kimi_local`)

Use this for Kimi models, whose Hugging Face repos ship a tiktoken BPE file instead of a single `tokenizer.json`. The tokenizer is vendored as a directory `tokenizers/<name>/` holding `tiktoken.model` and `tokenizer_config.json`, and counting runs offline with tiktoken.

1. Add one entry (local name, Hugging Face repo, pinned revision sha) to `KIMI_TOKENIZERS` in `scripts/fetch_tokenizers.py`, then run `.venv/bin/python scripts/fetch_tokenizers.py` from the repo root. It vendors `KIMI_FILES` into `tokenizers/<name>/`.
2. Append a `Model(provider="kimi", model="<name>-local", family="kimi_local", strategy="kimi_local", key_env=None, tokenizer_file="tokenizers/<name>")` row to `REGISTRY` in `src/tokencount/models.py`.
3. Add the pinned count for the known test string to `EXPECTED_KIMI_LOCAL` in `tests/test_counters.py`. Get the integer with:

   ```
   PYTHONPATH=src .venv/bin/python -c "from tokencount import kimi; print(kimi.count(kimi.load_encoding('tokenizers/<name>'), 'The quick brown fox jumps over the lazy dog. 0123456789'))"
   ```

4. Update the registry size pin in `tests/test_models.py` and run the tests.

## Corpus

The committed source of truth is `corpus/eu-members.txt` (Wikipedia pages, one per EU member) and `corpus/repos.txt` (one pinned file from a top GitHub repo per language). Add a line to either file to add a corpus entry. On a run the tool fetches each entry live into the gitignored `samples/` directory and reuses the cached file unless `--fresh` is given. Results key on the sha256 of the file content.
