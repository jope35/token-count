# token-count
how many tokens does the tokenzier use aka how to scale token prices between models

The tool counts, for every supported model, how many tokens that model's tokenizer produces for each file in a fixed corpus. It writes one row per (model, file) pair to `results/results.csv` and renders `results/table.md`, a Markdown table with models as rows and file types as columns.

## Quickstart

1. Install [uv](https://docs.astral.sh/uv/) (for example `brew install uv`). uv also installs the Python version from `.python-version` (3.14) automatically.
2. Run `uv sync` from the repo root. This creates `.venv` from `pyproject.toml` and the committed `uv.lock`. After changing dependencies, run `uv lock`, commit the updated `uv.lock`, and re-run `uv sync`.

## Run

From the repo root:

```
PYTHONPATH=src .venv/bin/python -m tokencount
```

This downloads the corpus into `samples/` (cached unless `--fresh` is given), counts every (model, file) pair, appends rows to `results/results.csv`, and writes `results/table.md`. The CLI entry (`__main__.py` and `run.py`) lands with plan B. Until then, that command fails with `No module named tokencount.__main__`; use the smoke check below to run what exists today.

## Secrets

API keys come from the environment. Either export them (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `Z_AI_API_KEY`, `MOONSHOT_API_KEY`) or copy `.env.example` to `.env`, fill in the values, and keep it local (`.env` is gitignored; the runner loads it, and process environment variables win over it). Every key is optional: a missing key is reported per model as `missing key <ENV>`, never an abort.

## Smoke check (works today)

```
PYTHONPATH=src .venv/bin/python -c "from tokencount.corpus import load_entries, fetch_corpus; samples = fetch_corpus(load_entries()); print(len(samples), 'samples fetched, e.g.', samples[0].path)"
```

This fetches all 32 corpus entries live into `samples/` and prints the count. It exercises the real fetch path, including the `User-Agent` header that Wikipedia requires.

## Corpus

The committed source of truth is `corpus/eu-members.txt` and `corpus/repos.txt`. On a run the tool fetches each entry live into the gitignored `samples/` directory and reuses the cached file unless `--fresh` is given. Results key on the sha256 of the file content, so a changed page is recounted automatically.

## Tests

Run from the repo root:

- Today (plan A): `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding tests.test_corpus_data tests.test_corpus`
- Plans B and C add `tests.test_models`, `tests.test_run`, `tests.test_table`, and `tests.test_counters`, all in the same `.venv`.
