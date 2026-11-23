# Design: token-count comparison table (2026-11-23)

## Intent and why

Different models tokenize the same text differently. The front page of Wikipedia costs about 200 tokens on an OpenAI model and about 300 on a Claude model. This project measures that gap on real files. It counts, for every supported model, how many tokens the model tokenizer produces for each sample file, and it publishes the result as a Markdown table with models on the vertical axis and file types on the horizontal axis.

## Goals

- One command runs the full measurement and regenerates the table.
- Every cell is the exact token count of that model for that file. No estimates.
- Every measurement is logged to CSV, so the table can be rebuilt without new API calls.

## Non-goals

- No inference. The tool never generates text. Counting endpoints do not bill inference.
- No chat-template overhead in the numbers. Cells count the raw file text, so cells stay comparable across providers.
- No per-file table. The table aggregates per file type. Per-file detail lives in the CSV.

## Metric definition

A cell counts the tokens of the raw file text for that model. Message-based counting APIs (Anthropic, Z.ai, Kimi) wrap a user message in fixed role tokens. The tool measures that wrapper once per model per run with a one-character user message and subtracts it. Google countTokens accepts a single text part, which adds no wrapper, and the OpenAI input token count is probed the same way. The builder verifies at build time that each wrapper is constant across content sizes and is zero where the endpoint adds none. Local tokenizers encode the raw text directly, so no baseline is needed there.

## Constraints

- Python project managed with uv. `uv sync` must set up everything.
- Secrets live in `.env` and never enter git. `.env.example` is committed with empty values.
- Counting is free on every provider used: OpenAI input token count, Anthropic count_tokens, Google countTokens, Z.ai tokenizer, Kimi estimate-token-count.
- Local strategies need no key, so a partial run works offline.

## Approaches considered

1. Count everything through provider APIs. Rejected: DeepSeek and Mistral expose no token-counting endpoint.
2. Count everything locally. Rejected: Anthropic and Google publish no tokenizer, so their rows would be approximations, and the point of the table is exact per-model numbers.
3. Hybrid (chosen): official free counting endpoints for OpenAI, Anthropic, Google, Z.ai and Kimi. Official tokenizer files from Hugging Face for DeepSeek and Mistral, because both publish open weights and no endpoint.

## Model registry (as of 2026-11-23)

Strategy `openai_api`: POST `/v1/responses/input_tokens/count` (free, key `OPENAI_API_KEY`).

- gpt-6.2-astra
- gpt-6.2-sol
- gpt-6.1-terra

Strategy `anthropic_api`: POST `/v1/messages/count_tokens` (free, key `ANTHROPIC_API_KEY`, header `anthropic-version: 2026-10-21`).

- claude-fable-5-2
- claude-opus-5-5
- claude-sonnet-5-5

Strategy `google_api`: POST `:countTokens` on `generativelanguage.googleapis.com` (key `GOOGLE_API_KEY`).

- gemini-4-neon
- gemini-4-hydrogen
- gemini-4-carbon

Strategy `hf_local`: vendored `tokenizers/` file for each model (no key, works offline).

- deepseek-flash (DeepSeek-V4.1-Flash-1017)
- deepseek-v4-pro (DeepSeek-V4-Pro-0813)

Note: DeepSeek currently serves only two models, so this provider has two rows, not three.

Strategy `zai_api`: POST `https://api.z.ai/api/paas/v4/tokenizer` (key `Z_AI_API_KEY`).

- glm-5.4
- glm-5.3
- glm-5.3-flash

Note: glm-5.4 shipped on 2026-11-23 without a public Model API yet. If the tokenizer endpoint rejects it, the cell is recorded as n/a. The registry is data, so updating rows is a one-line edit.

Strategy `kimi_api`: POST `https://api.moonshot.ai/v1/tokenizers/estimate-token-count` (key `MOONSHOT_API_KEY`).

- kimi-k3.1-pro
- kimi-k3.1-pro-highspeed
- kimi-k3

Strategy `hf_local`: vendored tekken `tokenizers/` file for each model (no key, works offline).

- mistral-large-4
- mistral-small-2603
- ministral-3-14b

Total: 20 rows.

## Corpus

The corpus is a fixed list of URLs, one entry per (file type, file name), kept in `src/tokencount/corpus.py`. File types: python, javascript, markdown, json, html, css, text. The html entry is the Wikipedia front page, matching the original example. On a run the tool downloads each URL with httpx into `samples/<file-type>/<name>` and reuses the cached file unless `--fresh` is given. `samples/` is gitignored; the URL list is the committed source of truth. Because the CSV keys on the sha256 of the file content, a page that changed is recounted automatically. The horizontal axis is driven by the file types in the corpus list. Columns: one per file type plus a Total column. A cell is the sum of tokens over all files of that type for that model.

Decision recorded from the owner (2026-11-23): fetch live at run time, accepting that counts drift when a source page changes.

## Pipeline

`uv run python -m tokencount` does the following.

1. Load `.env` with python-dotenv.
2. Read the model registry, download any missing corpus URLs into `samples/`, and read the sample files.
3. For each file and model pair, count tokens with the model strategy. Append one row per pair to `results/results.csv` with columns: timestamp, provider, model, strategy, file, file_type, sha256, chars, tokens, note. The dedup key is (model, strategy, file path, sha256 of the file content). A pair whose key is already present in the CSV is skipped, so reruns are incremental and an edited file is recounted. `--fresh` ignores the CSV and recounts everything.
4. Pivot the CSV into a Markdown table (rows: model, columns: file type plus Total) and write it to `results/table.md`. Print the same table to stdout. The Total column sums the numeric cells of a row.

Failure handling: a failed count writes the row with an empty tokens value and a note, and the run continues. The note says `error: <message>` for a failed call, `n/a` for a model the endpoint does not support (for example glm-5.4 before Z.ai publishes its API), and `missing key <ENV>` when the strategy's API key is absent. The table renders the cell as `error`, `n/a`, or `key`.

## Project layout

- `pyproject.toml`, `.python-version`, `uv.lock` (uv)
- `.env.example`, `.gitignore` (`.env`, `.venv`, `__pycache__`, `samples/`)
- `src/tokencount/__main__.py` (CLI entry)
- `src/tokencount/corpus.py` (fixed URL list: file type, file name, URL)
- `src/tokencount/models.py` (registry: provider, model id, strategy, key env var, vendored tokenizer file)
- `src/tokencount/counters.py` (one function per strategy, plus the baseline subtraction)
- `src/tokencount/run.py` (loop over files and models, CSV logging)
- `src/tokencount/table.py` (pivot and Markdown render)
- `tokenizers/<provider>-<model>.json` (vendored tokenizer files, committed, so local counts work offline and stay reproducible)
- `scripts/fetch_tokenizers.py` (downloads the vendored files from Hugging Face; run once when the registry changes)
- `samples/<type>/...`
- `tests/test_counters.py` (known vector for a local tokenizer, using the vendored files), `tests/test_table.py` (pivot from a small in-memory CSV)
- `README.md` (setup and usage)
- `results/results.csv`, `results/table.md` (generated and committed)

Dependencies: httpx, python-dotenv, tiktoken, tokenizers. No provider SDKs and no huggingface-hub at run time. All endpoints are plain REST and the fetch script uses plain HTTPS.

## Builder check decisions (author's calls, 2026-11-23)

- Dedup key and CSV schema: as in Pipeline. Call of the author.
- Baseline subtraction applies to message-based endpoints; each endpoint's wrapper is verified at build time. Call of the author.
- Tokenizer files are vendored and committed, not downloaded at run time. Call of the author.
- `error`, `n/a` and `missing key` are three note states rendered as `error`, `n/a`, `key`; Total sums numeric cells only. Call of the author.

## What is left to the builder

- The Hugging Face repo ids live in `scripts/fetch_tokenizers.py`; verify them once when vendoring the tokenizer files.
- The exact Google countTokens route, and whether the key goes in the query string or a header.
- Confirm each API wrapper is constant across content sizes and zero where the endpoint adds none (see Metric definition).
- Rate limiting: add a small delay between API calls and one retry on HTTP 429.

## Risks

- glm-5.4 may be uncountable until Z.ai publishes its API. The cell then shows n/a.
- Provider model ids change over time. The registry is data, so updates are one-line edits.
- Counting endpoints can change shape. Each strategy is one small function, so fixes stay local.
