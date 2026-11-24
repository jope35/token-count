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

- Python, managed with uv, with one virtual environment per route instead of a single project env: a single `.venv-api/` shared by all API families, and one `.venv-<name>/` per local tokenizer (deepseek, mistral). `./devenv.sh` creates the base `.venv` plus these envs and installs each route's pinned requirements. The base `.venv` runs the orchestrator.
- Each env's dependencies are pinned in `requirements/<route>.txt` (`base.txt`, `api.txt`, `deepseek.txt`, `mistral.txt`), generated with `uv pip compile` and committed, so the setup is reproducible.
- Secrets are declared in a committed `secretspec.toml` and resolved with secretspec (Python SDK); values live in the SOPS-encrypted, committed `secrets.enc.yaml`, with an `env://` fallback for CI. See Secrets.
- Counting is free on every provider used: OpenAI input token count, Anthropic count_tokens, Google countTokens, Z.ai tokenizer, Kimi estimate-token-count.
- Local strategies need no key, so a partial run works offline.

## Secrets

Secret handling is based on secretspec with a SOPS-encrypted file as the storage basis. `secretspec.toml` is committed and declares the five API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `Z_AI_API_KEY`, `MOONSHOT_API_KEY`), each with `required = false`, so an absent key never aborts a run; it is reported per model as `missing key <ENV>` (see Pipeline). The default provider chain is `["sops", "env"]`: values are read first from `secrets.enc.yaml` through the `sops://` provider, then from process environment variables (`env://`), which is how CI injects keys without an age identity. The project-level provider chain is a secretspec 0.21+ feature, so the pin is `secretspec>=0.21,<0.22`.

- `secrets.enc.yaml` is encrypted with SOPS (age key service) and committed; only ciphertext enters git. `.sops.yaml` holds the creation rule with the age recipient and is also committed. The age identity stays out of the repo (for example `~/.config/age/key.txt`, exposed to SOPS via `SOPS_AGE_KEY_FILE`); `key.txt` and `*.age` are gitignored if kept locally.
- The `sops://` provider delegates to the `sops` CLI, so `sops` must be on `PATH` at run time, with an age identity available to it (`SOPS_AGE_KEY_FILE` or `SOPS_AGE_KEY`). `devenv.sh` checks for the binary and the identity and warns when either is missing.
- The base env installs the `secretspec` Python SDK (pinned in `requirements/base.txt`, replacing python-dotenv; the published wheel includes the `sops` provider, which is in the crate's default features, so `pip install secretspec` is enough). The orchestrator resolves `secretspec.toml` once at startup and exports the result into the environment (`set_as_env()`); each family subprocess receives only its own family's key. Secret scoping is per subprocess, not per env: the API families share `.venv-api`, but each still runs as its own subprocess with only its own key. Workers keep reading keys from `os.environ`, and the registry's key env vars are exactly the declared secret names.
- Setup on a new machine: install `sops`, generate an age identity (`age-keygen`), add its recipient to `.sops.yaml`, then set each key once (`secretspec set OPENAI_API_KEY --provider sops://secrets.enc.yaml`). `secretspec check` shows which keys are set without printing values. The run command is unchanged; resolution happens in-process.

## Environments and dispatch

Environments are split by route — the path a count takes — not by model family. All API families speak plain REST with the same dependencies, so they share one env; each local tokenizer gets its own env. Secret scoping stays at the subprocess level, so sharing `.venv-api` does not widen any key's exposure.

`devenv.sh` at the repo root does the following.

1. Create the base env: `uv venv .venv` and install `requirements/base.txt` (httpx and the secretspec Python SDK, pinned). Also check that the `sops` CLI is on `PATH` (required by the `sops://` provider; see Secrets) and warn if no age identity is configured.
2. Create the API env: `uv venv .venv-api` and install `requirements/api.txt` (httpx, tenacity, tiktoken — tiktoken only serves the OpenAI known-vector cross-check).
3. For each local tokenizer, create `.venv-<name>` and install `requirements/<name>.txt`: `.venv-deepseek` and `.venv-mistral`, each pinning the `tokenizers` library. The two envs are identical today; they stay separate so a future local tokenizer can need a different library or version.

Run: `PYTHONPATH=src .venv/bin/python -m tokencount`. The orchestrator (base env) resolves secrets via secretspec (see Secrets), downloads missing corpus files, and then runs one subprocess per family in that family's route env, with `PYTHONPATH=src` and only that family's key in the environment: `.venv-api/bin/python -m tokencount --family <family>` for openai, anthropic, google, glm and kimi; `.venv-deepseek/bin/python -m tokencount --family deepseek` and `.venv-mistral/bin/python -m tokencount --family mistral` for the local families. The subprocess counts every corpus file for that family's models and appends rows to `results/results.csv`. After all families finish, the orchestrator renders `results/table.md` from the CSV. Tests use stdlib unittest and run in the env that has the needed library: `.venv/bin/python -m unittest tests.test_table`, `.venv-api/bin/python -m unittest tests.test_counters` for the OpenAI cross-check, and `.venv-deepseek/bin/python -m unittest tests.test_counters` (or `.venv-mistral`) for the local tokenizer vectors.

## Approaches considered

1. Count everything through provider APIs. Rejected: DeepSeek and Mistral expose no token-counting endpoint.
2. Count everything locally. Rejected: Anthropic and Google publish no tokenizer, so their rows would be approximations, and the point of the table is exact per-model numbers.
3. Hybrid (chosen): official free counting endpoints for OpenAI, Anthropic, Google, Z.ai and Kimi. Official tokenizer files from Hugging Face for DeepSeek and Mistral, because both publish open weights and no endpoint.

## Model registry (as of 2026-11-23)

Strategy `openai_api`: POST `/v1/responses/input_tokens` (free, key `OPENAI_API_KEY`; verified against live docs 2026-11-23 — the REST path has no `/count` suffix, the SDK method name `responses.input_tokens.count` is not the URL). Counts include message formatting tokens, so the baseline probe applies.

- gpt-6.2-astra
- gpt-6.2-sol
- gpt-6.1-terra
- gpt-6-luna

Strategy `anthropic_api`: POST `/v1/messages/count_tokens` (free, key `ANTHROPIC_API_KEY`, header `anthropic-version: 2026-10-21`).

- claude-fable-5-2
- claude-opus-5-5
- claude-sonnet-5-5
- claude-haiku-5-5

Strategy `google_api`: POST `:countTokens` on `generativelanguage.googleapis.com` (key `GOOGLE_API_KEY`).

- gemini-4-neon
- gemini-4-hydrogen
- gemini-4-carbon

Strategy `hf_local`: vendored `tokenizers/` file for each model (no key, works offline).

- deepseek-flash (DeepSeek-V4.1-Flash-1017)
- deepseek-v4-pro (DeepSeek-V4-Pro-0813)

Note: DeepSeek currently serves only two models, so this provider has two rows, not three.

Strategy `zai_api`: POST `https://api.z.ai/api/paas/v4/tokenizer` (key `Z_AI_API_KEY`, Bearer auth; the request requires `model` and a `messages` list with at least one user message; the response returns `usage.prompt_tokens`).

- glm-5.4
- glm-5.3
- glm-5.3-flash

Note: glm-5.4 shipped on 2026-11-23 without a public Model API yet. If the tokenizer endpoint rejects it, the cell is recorded as n/a. The registry is data, so updating rows is a one-line edit. Caution from a 2026-08-14 audit of the endpoint's OpenAPI: the documented model enum (`glm-4.6`, `glm-4.6v`, `glm-4.5` at that date) lagged GLM releases, so glm-5.3 and glm-5.3-flash need the same verification as glm-5.4, with n/a as the fallback.

Strategy `kimi_api`: POST `https://api.moonshot.ai/v1/tokenizers/estimate-token-count` (key `MOONSHOT_API_KEY`).

- kimi-k3.1-pro
- kimi-k3
- kimi-k2.7-code
- kimi-k2.6

Strategy `hf_local`: vendored tekken `tokenizers/` file for each model (no key, works offline).

- mistral-large-4
- mistral-small-2603
- mistral-medium-3-5


## Corpus

The corpus is a fixed list of URLs, one entry per (file type, file name), kept in `src/tokencount/corpus.py`. File types: python, javascript, markdown, json, html, css, text. The html entry is the Wikipedia front page, matching the original example. On a run the tool downloads each URL with httpx into `samples/<file-type>/<name>` and reuses the cached file unless `--fresh` is given. `samples/` is gitignored; the URL list is the committed source of truth. Because the CSV keys on the sha256 of the file content, a page that changed is recounted automatically. The horizontal axis is driven by the file types in the corpus list. Columns: one per file type plus a Total column. A cell is the sum of tokens over all files of that type for that model.

Decision recorded from the owner (2026-11-23): fetch live at run time, accepting that counts drift when a source page changes.

## Pipeline

`PYTHONPATH=src .venv/bin/python -m tokencount` does the following (see Environments and dispatch).

1. Resolve secrets with the secretspec Python SDK against `secretspec.toml` (SOPS file first, `env://` fallback) and export them into the environment. A resolution failure (missing `sops` CLI, undecryptable file) is caught and warned, never an abort: secretspec raises a provider error rather than reporting the secrets absent, so an unguarded failure would kill the run before the local families ever start. Each family subprocess receives only its own family's key; the other keys stay in the orchestrator.
2. Read the model registry, download any missing corpus URLs into `samples/`, and read the sample files.
3. For each family, run one subprocess in that family's route env, which counts each file and model pair with the model strategy. Append one row per pair to `results/results.csv` with columns: timestamp, provider, model, strategy, file, file_type, sha256, chars, tokens, note. The dedup key is (model, strategy, file path, sha256 of the file content). A pair whose key is already present in the CSV is skipped, so reruns are incremental and an edited file is recounted. `--fresh` ignores the CSV and recounts everything.
4. Pivot the CSV into a Markdown table (rows: model, columns: file type plus Total) and write it to `results/table.md`. Print the same table to stdout. The Total column sums the numeric cells of a row.

Failure handling: a failed count writes the row with an empty tokens value and a note, and the run continues. The note says `error: <message>` for a failed call, `n/a` for a model the endpoint does not support (for example glm-5.4 before Z.ai publishes its API), and `missing key <ENV>` when the strategy's API key is absent. The table renders the cell as `error`, `n/a`, or `key`.

## Project layout

- `devenv.sh` (creates the base env, the shared `.venv-api`, and one `.venv-<name>` per local tokenizer)
- `.python-version`, `requirements/base.txt`, `requirements/api.txt`, `requirements/<local-tokenizer>.txt` (pinned with `uv pip compile`, committed)
- `secretspec.toml` (committed secret declarations and provider chain), `secrets.enc.yaml` (SOPS-encrypted values, committed), `.sops.yaml` (age creation rule, committed), `.gitignore` (`.venv*`, `__pycache__`, `samples/`, `key.txt`, `*.age`)
- `src/tokencount/__main__.py` (CLI entry: orchestrator, or `--family <family>` worker)
- `src/tokencount/corpus.py` (fixed URL list: file type, file name, URL)
- `src/tokencount/models.py` (registry: provider, model id, family, route env, strategy, key env var, vendored tokenizer file)
- `src/tokencount/counters.py` (one function per strategy, plus the baseline subtraction; runs inside the route env)
- `src/tokencount/run.py` (orchestrator: fetch corpus, dispatch one subprocess per family in that family's route env, CSV append; worker: count one family)
- `src/tokencount/table.py` (pivot and Markdown render, stdlib only)
- `tokenizers/<provider>-<model>.json` (vendored tokenizer files, committed, so local counts work offline and stay reproducible)
- `scripts/fetch_tokenizers.py` (downloads the vendored files from Hugging Face; run once when the registry changes)
- `tests/test_counters.py` (known vector for each vendored tokenizer, run in `.venv-deepseek` or `.venv-mistral`; OpenAI tiktoken cross-check run in `.venv-api`), `tests/test_table.py` (pivot from a small in-memory CSV, run in `.venv`)
- `README.md` (setup and usage)
- `results/results.csv`, `results/table.md` (generated and committed)

Dependencies per env: the API route env `.venv-api` needs httpx and tenacity (pinned; used for the HTTP 429 retry and the inter-call delay) plus tiktoken for the OpenAI cross-check; the base env adds the secretspec Python SDK (which drives the `sops` CLI, so `sops` itself is a system prerequisite, not a pip package); the local tokenizer envs (`.venv-deepseek`, `.venv-mistral`) add tokenizers. No provider SDKs and no huggingface-hub at run time. All endpoints are plain REST and the fetch script uses plain HTTPS.

## Builder check decisions (author's calls, 2026-11-23)

- Dedup key and CSV schema: as in Pipeline. Call of the author.
- Baseline subtraction applies to message-based endpoints; each endpoint's wrapper is verified at build time. Call of the author.
- Tokenizer files are vendored and committed, not downloaded at run time. Call of the author.
- `error`, `n/a` and `missing key` are three note states rendered as `error`, `n/a`, `key`; Total sums numeric cells only. Call of the author.
- One env per route via `devenv.sh` — a single shared `.venv-api` for all API families, one env per local tokenizer — with pinned per-route requirements, for reproducibility. Subprocesses stay per family, so each family process still sees only its own key. Decision of the owner (2026-11-23).
- Secret handling: secretspec manifest with the committed SOPS-encrypted `secrets.enc.yaml` (`sops://`) as the basis, `env://` fallback for CI, and all keys `required = false` so partial offline runs still work. Decision of the owner (2026-11-23).

## What is left to the builder

- The Hugging Face repo ids live in `scripts/fetch_tokenizers.py`; verify them once when vendoring the tokenizer files.
- The exact Google countTokens route, and whether the key goes in the query string or a header.
- Confirm each API wrapper is constant across content sizes and zero where the endpoint adds none (see Metric definition).
- Rate limiting: add a small delay between API calls and one retry on HTTP 429, use tenacity
- Verify the `anthropic-version` value (`2026-10-21`) and the Kimi `estimate-token-count` route on `api.moonshot.ai` against current official docs at first run; neither was verifiable at review time.
- Secrets setup: generate the age identity, put its recipient in `.sops.yaml`, create `secrets.enc.yaml`, and populate the five keys with `secretspec set`; pin the `secretspec` SDK version in `requirements/base.txt` and confirm the installed `sops` CLI decrypts the file.

## Risks

- glm-5.4 may be uncountable until Z.ai publishes its API. The cell then shows n/a.
- A counting endpoint can accept a model outside its documented enum and count it with a different tokenizer, returning a plausible wrong number instead of an error. The first count per model is cross-checked against a known vector before that family's rows are trusted (see Verification and validation).
- Provider model ids change over time. The registry is data, so updates are one-line edits.
- Counting endpoints can change shape. Each strategy is one small function, so fixes stay local.
- Fetched corpus pages change over time, so historical CSV rows and the current table can drift apart. The sha256 key keeps recounts correct; it does not freeze the past.
- The age identity is the only way to decrypt `secrets.enc.yaml`; losing it means re-issuing every provider key. Keep it backed up outside git.
- secretspec and sops move independently; the SDK is pinned in `requirements/base.txt` and the `sops` CLI version is noted in the README, but the `sops://` provider's behavior can still change between them.

## Verification and validation

Success criteria: one command (`PYTHONPATH=src .venv/bin/python -m tokencount`) regenerates `results/table.md` with a numeric or note cell for every (model, file type) pair, and a rerun over an unchanged corpus adds no rows to `results/results.csv`.

- Secrets preflight (per machine, before the first run): `secretspec check` lists all five keys as set without printing values, and a unit test resolves one key from a fixture SOPS-encrypted file through the SDK. A failure here stops the run loudly; it never degrades to empty keys silently.
- Offline partial run: with all five keys unset and `sops` absent from `PATH`, the run still completes — deepseek and mistral rows are numeric, all API-family rows carry `missing key <ENV>`, exit code 0. This proves the resolution-failure guard in Pipeline step 1.
- Least privilege: a unit test on the dispatch environment asserts each family subprocess sees only its own family's key env var.
- Baseline wrapper (Metric definition): for each message-based strategy, counts for 1-, 2-, and 3-character user messages differ by exactly the content delta, proving the wrapper constant; for Google and OpenAI, a plain string input is compared against the wrapped form to prove the wrapper is zero.
- Known vectors: `tests/test_counters.py` pins a fixed string against each vendored tokenizer file. For every API strategy, the first count per model is cross-checked against a known vector for the same fixed string; a mismatch invalidates that family's rows for the run (see Risks on silent model aliasing).
- Idempotency: a second run over an unchanged corpus adds zero CSV rows (dedup key test in `tests/test_table.py`); `--fresh` recounts everything.
- End-to-end: after a full run, `results/table.md` has one row per registry model and one column per corpus file type plus Total, and every Total equals the sum of its numeric cells.
