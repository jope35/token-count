# Plan B: counting-API pathway — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the counting-API pathway: the model registry for the five API families, one plain-httpx REST counter per family with baseline subtraction, and the orchestrator/worker CLI that appends deduplicated rows to `results/results.csv`.

**Architecture:** `models.py` holds the registry as data. `counters.py` holds one small function per API strategy plus the baseline subtraction and runs inside `.venv-api`. `run.py` is the CLI. With no arguments it runs the orchestrator in the base `.venv`: it resolves secrets with secretspec, fetches the corpus through plan A, and dispatches one subprocess per family with only that family's key. With `--family X` it runs the worker: it counts every sample for the family's models and appends CSV rows. This plan depends on plan A: the envs, `src/tokencount/corpus.py`, and the secretspec files must exist first.

**Tech Stack:** Python 3, httpx, tenacity and tiktoken in `.venv-api`, secretspec>=0.21,<0.22 in `.venv`, stdlib unittest. Plain REST only, no provider SDKs.

**Spec:** docs/superpowers/specs/2026-11-23-token-count-table-design.md

## Global Constraints

- Plan split (owner, 2026-11-24): plan B owns `src/tokencount/models.py`, `src/tokencount/counters.py` (only the five API strategies), `src/tokencount/run.py`, `src/tokencount/__main__.py`, `tests/test_models.py`, `tests/test_counters.py`, `tests/test_run.py`. Plan A owns the base environment, the route envs, and the corpus. Plan C owns `src/tokencount/table.py`, the real `render_results()`, the `hf_local` strategy, and the `.venv-deepseek`/`.venv-mistral` routes. Plan B leaves a marked `render_results()` call site in `run.py`.
- Corpus (owner, 2026-11-24): plan A locks the samples in `corpus/eu-members.txt` and `corpus/repos.txt`; plan B only consumes `load_entries() -> list[CorpusEntry]` and `fetch_corpus(entries, dest_dir="samples", fresh=False) -> list[Sample]` from `src/tokencount/corpus.py`, where `Sample` has fields (path, file_type, name, sha256, chars, text). Plan B calls `fetch_corpus(load_entries(), fresh=fresh)` with the default `dest_dir="samples"` from the repo root and writes `sample.path` verbatim into the CSV `file` column and the dedup key — the relative string `samples/<file_type>/<name>`, member names without extension (e.g. `samples/text/France`), repo entries by repo short name (e.g. `samples/python/public-apis`). Another CWD or dest_dir silently changes dedup keys, so a test asserts every written `file` starts with `samples/`. `chars` is `len()` of the decoded text (characters) and `sha256` is over the raw bytes (plan A contract); the CSV carries both and the test fixture uses non-ASCII text so the two units cannot be mixed silently. `fetch_corpus` raises on HTTP error (plan A): a failed fetch aborts the run before any CSV row is written, so a fetch failure never yields a partial sample list or a half-updated `results/results.csv`; plan C's offline end-to-end therefore needs network for the 32 fetches or a warm `samples/` cache.
- Envs: `.venv` (httpx, secretspec>=0.21,<0.22) runs the orchestrator and `tests/test_run`; `.venv-api` (httpx, tenacity, tiktoken) runs all five API-family workers and `tests/test_counters`.
- Run: `PYTHONPATH=src .venv/bin/python -m tokencount`. Tests: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run`, `PYTHONPATH=src .venv-api/bin/python -m unittest tests.test_counters`, `PYTHONPATH=src .venv/bin/python -m unittest tests.test_models`.
- Secrets: `secretspec.toml` declares OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, Z_AI_API_KEY, MOONSHOT_API_KEY, each with required=false and provider chain ["sops","env"]. A resolution failure prints a warning on stderr and never aborts: `resolve_secrets` catches the SDK's `SecretSpecError` specifically — the SDK raises it when a reached provider fails (missing sops CLI, undecryptable `secrets.enc.yaml`), while an absent key with required=false resolves silently and never raises, and `MissingRequiredError` cannot occur at all here (https://secretspec.dev/sdk/python/, https://secretspec.dev/concepts/providers/fallback/). Each family subprocess receives only its own family's key.
- Registry (owner, 2026-11-24): openai_api with OPENAI_API_KEY: gpt-6.2-astra, gpt-6.2-sol, gpt-6.1-terra, gpt-6.1-luna. anthropic_api with ANTHROPIC_API_KEY: claude-fable-5-2, claude-opus-5-5, claude-sonnet-5-5, claude-haiku-5-5. google_api with GOOGLE_API_KEY: gemini-4-neon, gemini-4-hydrogen, gemini-4-carbon. zai_api with Z_AI_API_KEY: glm-5.4, glm-5.3, glm-5.3-flash. kimi_api with MOONSHOT_API_KEY: kimi-k3.1-pro, kimi-k3, kimi-k2.7-code, kimi-k2.6. All five families route to `.venv-api`.
- CSV: columns exactly `timestamp,provider,model,strategy,file,file_type,sha256,chars,tokens,note`; dedup key (model, strategy, file, sha256); `--fresh` ignores the CSV dedup and re-downloads the corpus (Task 4); a failed count writes an empty tokens value plus a note and the run continues. Only rows with a numeric `tokens` or note `n/a` / `missing key <ENV>` join the dedup set — `error:` rows are not deduped, so a transient failure (exhausted 429 retries, timeout) is retried on the next run instead of being cached forever. Each row is appended with a single write call; `read_dedup_keys` skips a malformed trailing line (torn write from a killed process) so that pair is recounted.
- Note states: `error: <message>`, `n/a`, `missing key <ENV>`.
- Metric: a cell counts the raw file text. `baseline_tokens` returns 0 for google_api (a single text part adds no wrapper). For anthropic_api, zai_api, and kimi_api it probes a 1-char user message once per (strategy, model) per process and returns the probe count minus 1 (the probe character's own token; Task 3 pins live that a 1-char input counts as exactly 1 after subtraction). For openai_api it also returns 0, but that zero must be proven live: a string `input` is sent as a user-role message and the endpoint count includes message formatting tokens (developers.openai.com/api/docs/guides/token-counting), so Task 3 asserts the tiktoken vector match and a 1-char count of 1; if the wrapper is not zero, probe openai_api like the message-based strategies and update the Task 2 mocks. `count_tokens` returns raw minus baseline.
- HTTP: plain httpx REST. Tenacity retries HTTP 429 (3 attempts) and a small sleep runs between calls. HTTP 400 or 404 for an unknown model raises UnsupportedModelError, which the worker maps to `n/a`.
- Endpoints (spec registry section): openai POST https://api.openai.com/v1/responses/input_tokens; anthropic POST https://api.anthropic.com/v1/messages/count_tokens with header `anthropic-version: 2026-10-21`; google POST https://generativelanguage.googleapis.com/v1beta/models/<model>:countTokens; zai POST https://api.z.ai/api/paas/v4/tokenizer with Bearer auth, body model plus messages with at least one user message, response usage.prompt_tokens; kimi POST https://api.moonshot.ai/v1/tokenizers/estimate-token-count. Verified against the official docs on 2026-11-24: OpenAI `POST /v1/responses/input_tokens` is free of inference quota and returns `input_tokens` with Bearer auth (developers.openai.com/api/docs/guides/token-counting; help.openai.com/en/articles/4936856); Anthropic `POST /v1/messages/count_tokens` returns `input_tokens`, the header `anthropic-version: 2026-10-21` is the value used in the official example, and no `anthropic-beta` header is needed (`token-counting-2024-11-01` is deprecated) (platform.claude.com/docs/en/api/messages/count_tokens); Google `POST /v1beta/models/<model>:countTokens` on generativelanguage.googleapis.com accepts the key as the `key` query param or the `x-goog-api-key` header and returns `totalTokens` (aistudio.google.com/api-reference/tokens/count-tokens); Z.ai `POST https://api.z.ai/api/paas/v4/tokenizer` with Bearer auth returns `usage.prompt_tokens`, but its published OpenAPI model enum still lists only glm-4.x models (docs.z.ai/api-reference/tools/tokenizer), so glm-5.x rows depend on the 400→`n/a` path; Kimi `POST https://api.moonshot.ai/v1/tokenizers/estimate-token-count` returns `data.total_tokens` — not `token_count` (platform.kimi.ai/docs/api/estimate).

## Review Focus

1. Silent model aliasing: an endpoint accepts an undocumented model id and counts with a different tokenizer, so the cell looks plausible but is wrong. Pinned by the Task 3 live known-vector tests (they run only when the key is present).
2. Wrapper drift: the baseline subtraction assumes a constant message wrapper; if the wrapper grows with content size, every cell is wrong. Pinned by the Task 3 wrapper-constancy test: counts for 1-, 2-, and 3-char user messages differ by exactly the content delta, and the wrapper is zero for google and openai.
3. Key leakage: a family subprocess sees another family's key. Pinned by Task 4 `test_least_privilege` on `family_env`.
4. Secrets failure aborts the run: a missing sops CLI or an undecryptable file raises a provider error. Pinned by Task 4 `test_provider_error_warns_and_continues` and the Task 5 offline partial run (exit 0 with `missing key <ENV>` rows).
5. Dedup misfires: a rerun recounts everything, a changed file is skipped, or a transient `error:` row is cached forever. Pinned by Task 4 `test_dedup_skips_existing_pair`, `test_error_rows_are_recounted_on_rerun`, `test_torn_trailing_row_is_not_a_dedup_key`, and `test_fresh_recounts_everything` (which also pins `--fresh` reaching the orchestrator's own `fetch_corpus` call, not just the workers).
6. Silent partial run: a crashed family worker is ignored and the orchestrator still exits 0. Pinned by Task 4 `test_failed_worker_makes_main_nonzero_but_still_renders`.

### Task 1: Model registry for the five API families

**Files:**
- Create: `src/tokencount/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing from plan A (stdlib only).
- Produces: in `src/tokencount/models.py`, `@dataclass Model(provider, model, family, strategy, key_env, tokenizer_file)` with `tokenizer_file: str | None = None`, `REGISTRY: list[Model]`, and `models_for_family(family) -> list[Model]`. Tasks 2 and 4 and plan C read only these three names. Plan C appends `hf_local` rows to `REGISTRY` as data, without editing the code.

- [ ] **Step 1: Write the failing test** in `tests/test_models.py`:

```python
import unittest

from tokencount.models import REGISTRY, models_for_family

EXPECTED = {
    "openai": ("openai_api", "OPENAI_API_KEY",
               ["gpt-6.2-astra", "gpt-6.2-sol", "gpt-6.1-terra", "gpt-6.1-luna"]),
    "anthropic": ("anthropic_api", "ANTHROPIC_API_KEY",
                  ["claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]),
    "google": ("google_api", "GOOGLE_API_KEY",
               ["gemini-4-neon", "gemini-4-hydrogen", "gemini-4-carbon"]),
    "glm": ("zai_api", "Z_AI_API_KEY", ["glm-5.4", "glm-5.3", "glm-5.3-flash"]),
    "kimi": ("kimi_api", "MOONSHOT_API_KEY",
             ["kimi-k3.1-pro", "kimi-k3", "kimi-k2.7-code", "kimi-k2.6"]),
}
KNOWN_STRATEGIES = {"openai_api", "anthropic_api", "google_api", "zai_api", "kimi_api", "hf_local"}


class TestRegistry(unittest.TestCase):
    def test_unique_model_ids_and_count(self):
        ids = [m.model for m in REGISTRY]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(REGISTRY), 18)

    def test_families_strategies_keys_models(self):
        for family, (strategy, key_env, models) in EXPECTED.items():
            got = models_for_family(family)
            self.assertEqual([m.model for m in got], models)
            for m in got:
                self.assertEqual(m.provider, family)
                self.assertEqual(m.family, family)
                self.assertEqual(m.strategy, strategy)
                self.assertEqual(m.key_env, key_env)
                self.assertIsNone(m.tokenizer_file)

    def test_strategy_in_known_set(self):
        for m in REGISTRY:
            self.assertIn(m.strategy, KNOWN_STRATEGIES)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_models -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tokencount'`

- [ ] **Step 3: Implement the registry in `src/tokencount/models.py`**

`@dataclass Model` with the six fields above; `REGISTRY` built from a per-family table holding the exact 18 model ids, with `provider` equal to the family name and `tokenizer_file=None`; `models_for_family(family)` filters `REGISTRY` by `family`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_models -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add src/tokencount/models.py tests/test_models.py
git commit -m "feat: model registry for the five API families"
```

### Task 2: API counters with baseline subtraction

**Files:**
- Create: `src/tokencount/counters.py`
- Test: `tests/test_counters.py`

**Interfaces:**
- Consumes: nothing from plan A beyond the env (httpx, tenacity in `.venv-api`).
- Produces for Task 4 and plan C, all in `src/tokencount/counters.py`: `count_tokens(strategy: str, model_id: str, text: str, key: str | None = None, tokenizer_file: str | None = None) -> int`; `baseline_tokens(strategy: str, model_id: str, key: str) -> int`; `class MissingKeyError(Exception)` with attribute `env`; `class UnsupportedModelError(Exception)`; `STRATEGY_KEY_ENV` mapping the five strategies to their key env names; module constants `TRANSPORT` (test hook, `None` in production), `RETRY_WAIT_SECONDS`, `CALL_DELAY_SECONDS`, and `_BASELINE_CACHE`. One small private function per strategy. `hf_local` raises `ValueError` because plan C owns it.

- [ ] **Step 1: Write the failing tests** in `tests/test_counters.py` (unit part, httpx MockTransport injected via `counters.TRANSPORT`):

```python
import json
import unittest

import httpx

from tokencount import counters


def use_mock(handler):
    counters.TRANSPORT = httpx.MockTransport(handler)


class CounterTestCase(unittest.TestCase):
    def setUp(self):
        counters.TRANSPORT = None
        counters._BASELINE_CACHE.clear()
        counters.RETRY_WAIT_SECONDS = 0
        counters.CALL_DELAY_SECONDS = 0

    def tearDown(self):
        counters.TRANSPORT = None
        counters._BASELINE_CACHE.clear()


class TestApiStrategies(CounterTestCase):
    def test_openai_parses_input_tokens(self):
        def handler(request):
            assert request.url.path == "/v1/responses/input_tokens"
            assert request.headers["authorization"] == "Bearer k"
            assert json.loads(request.content) == {"model": "gpt-6.2-astra", "input": "hello"}
            return httpx.Response(200, json={"input_tokens": 42})
        use_mock(handler)
        self.assertEqual(counters.count_tokens("openai_api", "gpt-6.2-astra", "hello", key="k"), 42)

    def test_anthropic_version_header_and_baseline_subtraction(self):
        seen = []
        def handler(request):
            assert request.url.path == "/v1/messages/count_tokens"
            assert request.headers["anthropic-version"] == "2026-10-21"
            assert request.headers["x-api-key"] == "k"
            text = json.loads(request.content)["messages"][0]["content"]
            seen.append(text)
            return httpx.Response(200, json={"input_tokens": 10 + len(text)})
        use_mock(handler)
        self.assertEqual(counters.count_tokens("anthropic_api", "claude-sonnet-5-5", "abc", key="k"), 3)
        self.assertEqual(seen[0], "x")

    def test_anthropic_baseline_cached_per_model(self):
        seen = []
        def handler(request):
            text = json.loads(request.content)["messages"][0]["content"]
            seen.append(text)
            return httpx.Response(200, json={"input_tokens": 10 + len(text)})
        use_mock(handler)
        counters.count_tokens("anthropic_api", "claude-sonnet-5-5", "ab", key="k")
        counters.count_tokens("anthropic_api", "claude-sonnet-5-5", "abcd", key="k")
        self.assertEqual(seen, ["x", "ab", "abcd"])

    def test_google_route_query_key_and_zero_baseline(self):
        calls = []
        def handler(request):
            calls.append(request)
            assert request.url.host == "generativelanguage.googleapis.com"
            assert request.url.path.endswith(":countTokens")
            assert request.url.params["key"] == "k"
            return httpx.Response(200, json={"totalTokens": 9})
        use_mock(handler)
        self.assertEqual(counters.count_tokens("google_api", "gemini-4-neon", "abc", key="k"), 9)
        self.assertEqual(len(calls), 1)

    def test_zai_usage_prompt_tokens(self):
        def handler(request):
            assert str(request.url) == "https://api.z.ai/api/paas/v4/tokenizer"
            assert request.headers["authorization"] == "Bearer k"
            body = json.loads(request.content)
            assert body["model"] == "glm-5.3"
            assert body["messages"][0]["role"] == "user"
            return httpx.Response(200, json={"usage": {"prompt_tokens": 5 + len(body["messages"][0]["content"])}})
        use_mock(handler)
        self.assertEqual(counters.count_tokens("zai_api", "glm-5.3", "abcd", key="k"), 4)

    def test_kimi_route(self):
        def handler(request):
            assert str(request.url) == "https://api.moonshot.ai/v1/tokenizers/estimate-token-count"
            body = json.loads(request.content)
            assert body["model"] == "kimi-k3"
            return httpx.Response(200, json={"data": {"total_tokens": 7 + len(body["messages"][0]["content"])}})
        use_mock(handler)
        self.assertEqual(counters.count_tokens("kimi_api", "kimi-k3", "ab", key="k"), 2)

    def test_missing_key_raises_missing_key_error(self):
        with self.assertRaises(counters.MissingKeyError) as cm:
            counters.count_tokens("openai_api", "gpt-6.2-astra", "x", key=None)
        self.assertEqual(cm.exception.env, "OPENAI_API_KEY")

    def test_429_retried_then_succeeds(self):
        state = {"n": 0}
        def handler(request):
            state["n"] += 1
            if state["n"] < 3:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json={"input_tokens": 5})
        use_mock(handler)
        self.assertEqual(counters.count_tokens("openai_api", "m", "x", key="k"), 5)
        self.assertEqual(state["n"], 3)

    def test_400_maps_to_unsupported_model(self):
        def handler(request):
            return httpx.Response(400, json={"error": {"message": "unknown model"}})
        use_mock(handler)
        with self.assertRaises(counters.UnsupportedModelError):
            counters.count_tokens("zai_api", "glm-5.4", "x", key="k")

    def test_baseline_zero_for_openai_and_google_without_http(self):
        def handler(request):
            raise AssertionError("no HTTP call expected")
        use_mock(handler)
        self.assertEqual(counters.baseline_tokens("openai_api", "m", "k"), 0)
        self.assertEqual(counters.baseline_tokens("google_api", "m", "k"), 0)

    def test_hf_local_rejected(self):
        with self.assertRaises(ValueError):
            counters.count_tokens("hf_local", "m", "x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src .venv-api/bin/python -m unittest tests.test_counters -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tokencount'`

- [ ] **Step 3: Implement `src/tokencount/counters.py`**

Signatures exactly as in Interfaces. `_post_json(url, *, headers, payload)` posts with `httpx.Client(transport=TRANSPORT)`, retries HTTP 429 with `tenacity.Retrying(stop=stop_after_attempt(3), wait=wait_fixed(RETRY_WAIT_SECONDS), retry=...)` constructed per call so tests can zero the waits, maps 400/404 to `UnsupportedModelError`, calls `raise_for_status` otherwise, and sleeps `CALL_DELAY_SECONDS` after each call. Import tenacity inside `_post_json` so the base `.venv` can import this module for the missing-key path. Each strategy function builds its request per the endpoint list in Global Constraints and parses its response field (openai `input_tokens`, anthropic `input_tokens`, google `totalTokens`, zai `usage.prompt_tokens`, kimi `data.total_tokens` — the official Kimi schema returns `data.total_tokens`, platform.kimi.ai/docs/api/estimate). `count_tokens` raises `MissingKeyError(STRATEGY_KEY_ENV[strategy])` when `key is None`, then gets the baseline first from `_BASELINE_CACHE` (probing the 1-char message `"x"` on first use, which is why the anthropic test sees `"x"` as the first request), then takes the raw count, and returns raw minus baseline. `baseline_tokens` returns 0 for google_api without any HTTP (a single text part adds no wrapper) and 0 for openai_api (proven zero by the Task 3 live tests; see Global Constraints); for anthropic_api, zai_api, and kimi_api it probes the 1-char message `"x"` once per (strategy, model) and returns the probe count minus 1 for the probe character's own token — that minus-1 is exactly what the Task 2 mocks encode (they return wrapper + len(content), so `count_tokens` must yield len(content)).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src .venv-api/bin/python -m unittest tests.test_counters -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add src/tokencount/counters.py tests/test_counters.py
git commit -m "feat: httpx REST counters for the five API strategies with baseline subtraction"
```

### Task 3: Live builder-verification tests for the five endpoints

**Files:**
- Modify: `tests/test_counters.py` (append the live test classes below)

**Interfaces:**
- Consumes: `counters.count_tokens`, `counters.baseline_tokens`, `counters.STRATEGY_KEY_ENV` from Task 2.
- Produces: proof, gated on key presence, that the routes, headers, and wrapper assumptions match the live APIs. No production code changes unless a test fails; then the fix is local to one strategy function in `counters.py`.

- [ ] **Step 1: Append the live tests** to `tests/test_counters.py` (add `import os` to the imports at the top, then append):

```python
class LiveTestCase(unittest.TestCase):
    def setUp(self):
        counters.TRANSPORT = None
        counters._BASELINE_CACHE.clear()


def live_key(strategy):
    return os.environ.get(counters.STRATEGY_KEY_ENV[strategy])


@unittest.skipUnless(live_key("openai_api"), "needs OPENAI_API_KEY")
class TestLiveOpenAI(LiveTestCase):
    def test_input_tokens_matches_tiktoken_vector(self):
        import tiktoken
        text = "The quick brown fox jumps over the lazy dog"
        expected = len(tiktoken.get_encoding("o200k_base").encode(text))
        got = counters.count_tokens("openai_api", "gpt-6.2-astra", text, key=live_key("openai_api"))
        self.assertEqual(got, expected)

    def test_single_char_counts_as_one_token(self):
        # A string input is a user-role message, so this also pins that the
        # input_tokens wrapper for openai_api is zero (baseline 0). If this
        # fails by a constant, switch openai_api to a probed baseline.
        got = counters.count_tokens("openai_api", "gpt-6.2-astra", "x", key=live_key("openai_api"))
        self.assertEqual(got, 1)


@unittest.skipUnless(live_key("anthropic_api"), "needs ANTHROPIC_API_KEY")
class TestLiveAnthropic(LiveTestCase):
    def test_anthropic_version_2026_10_21_accepted(self):
        n = counters.count_tokens("anthropic_api", "claude-sonnet-5-5", "hello world",
                                  key=live_key("anthropic_api"))
        self.assertGreater(n, 0)


@unittest.skipUnless(live_key("google_api"), "needs GOOGLE_API_KEY")
class TestLiveGoogle(LiveTestCase):
    def test_count_tokens_query_key_works_and_wrapper_is_zero(self):
        key = live_key("google_api")
        self.assertGreater(counters.count_tokens("google_api", "gemini-4-neon", "hello world", key=key), 0)
        self.assertLessEqual(counters.count_tokens("google_api", "gemini-4-neon", "a", key=key), 2)


@unittest.skipUnless(live_key("zai_api"), "needs Z_AI_API_KEY")
class TestLiveZai(LiveTestCase):
    def test_tokenizer_endpoint_counts(self):
        n = counters.count_tokens("zai_api", "glm-5.3", "hello world", key=live_key("zai_api"))
        self.assertGreater(n, 0)


@unittest.skipUnless(live_key("kimi_api"), "needs MOONSHOT_API_KEY")
class TestLiveKimi(LiveTestCase):
    def test_moonshot_route_counts(self):
        n = counters.count_tokens("kimi_api", "kimi-k3", "hello world", key=live_key("kimi_api"))
        self.assertGreater(n, 0)


class TestLiveWrapperConstancy(LiveTestCase):
    def test_message_based_wrapper_constant_across_sizes(self):
        for strategy, model in [("anthropic_api", "claude-sonnet-5-5"),
                                ("zai_api", "glm-5.3"),
                                ("kimi_api", "kimi-k3")]:
            key = live_key(strategy)
            if not key:
                continue
            with self.subTest(strategy=strategy):
                c1 = counters.count_tokens(strategy, model, "a", key=key)
                c2 = counters.count_tokens(strategy, model, "ab", key=key)
                c3 = counters.count_tokens(strategy, model, "abc", key=key)
                self.assertGreater(c2 - c1, 0)
                self.assertEqual(c2 - c1, c3 - c2)
                # pins the probe-minus-1 baseline: one character is one token
                self.assertEqual(counters.count_tokens(strategy, model, "x", key=key), 1)
```

- [ ] **Step 2: Run to verify the key gate works**

Run (no keys in the environment): `PYTHONPATH=src .venv-api/bin/python -m unittest tests.test_counters -v`
Expected: PASS, the 11 unit tests pass, the 5 key-gated classes report skipped, and the constancy test passes trivially. On a machine with keys set, the same command exercises the live endpoints; a failure there means the route, header, or wrapper assumption is wrong and the owning strategy function gets fixed.

- [ ] **Step 3: Implement**

No new code. If a live test fails when its key is present, fix only the one strategy function in `src/tokencount/counters.py` (route, header, key placement, or response field) and update the matching MockTransport test in Task 2 so both stay in agreement.

- [ ] **Step 4: Run to verify**

Run: `PYTHONPATH=src .venv-api/bin/python -m unittest tests.test_counters -v`
Expected: PASS (live classes skipped without keys, executed with keys)

- [ ] **Step 5: Commit**

```bash
git add tests/test_counters.py
git commit -m "test: live builder-verification tests for the five counting endpoints"
```

### Task 4: Orchestrator, per-family worker, CSV results, CLI entry

**Files:**
- Create: `src/tokencount/run.py`
- Create: `src/tokencount/__main__.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes (plan A): `from tokencount.corpus import CorpusEntry, Sample, fetch_corpus, load_entries` with `load_entries() -> list[CorpusEntry]` and `fetch_corpus(entries, dest_dir="samples", fresh=False) -> list[Sample]`. Consumes Task 1 `REGISTRY`, `models_for_family`. Consumes Task 2 `count_tokens`, `MissingKeyError`, `UnsupportedModelError`, imported lazily inside `run_worker` so the base `.venv` can run the orchestrator without tenacity.
- Produces for plan C: the `render_results()` call site in the orchestrator after all subprocesses finish, and the CSV contract at `results/results.csv` with `CSV_COLUMNS = ["timestamp","provider","model","strategy","file","file_type","sha256","chars","tokens","note"]`, dedup key (model, strategy, file, sha256), and note states `error: <message>`, `n/a`, `missing key <ENV>`.
- Produces for the contract: `main(argv=None)` in `run.py`; `family_env(family: str, secrets: dict) -> dict` returning `{"PYTHONPATH": "src"}` plus only that family's key when present; `route_env(family) -> ".venv-api"` for the five API families and `.venv-<family>` otherwise (so plan C's local families need no edit here); `run_worker(family, fresh=False, results_csv=None) -> int`; `resolve_secrets(path="secretspec.toml") -> dict`; `render_results() -> None` stub marked as the plan C hook.

- [ ] **Step 1: Write the failing tests** in `tests/test_run.py`:

```python
import contextlib
import csv
import hashlib
import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import httpx

from tokencount import counters, run
from tokencount.corpus import Sample

# Plan A contract shape: member names carry no extension and Sample.path is
# the relative string samples/<file_type>/<name>. sha256 is over the raw bytes
# while chars is len() of the decoded text, so the fixture is non-ASCII to
# pin the units (5 characters, 6 bytes).
SAMPLE = Sample(path="samples/text/France", file_type="text", name="France",
                sha256=hashlib.sha256("héllo".encode("utf-8")).hexdigest(),
                chars=5, text="héllo")


def fake_corpus(*args, **kwargs):
    return [SAMPLE]


FAMILY_KEY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "glm": "Z_AI_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
}
ALL_SECRETS = {k: k.lower() for k in FAMILY_KEY.values()}


class TestRouteEnv(unittest.TestCase):
    def test_api_families_route_to_venv_api(self):
        for family in FAMILY_KEY:
            self.assertEqual(run.route_env(family), ".venv-api")


class TestFamilyEnv(unittest.TestCase):
    def test_least_privilege(self):
        for family, key_env in FAMILY_KEY.items():
            env = run.family_env(family, ALL_SECRETS)
            self.assertEqual(env["PYTHONPATH"], "src")
            self.assertEqual(env[key_env], ALL_SECRETS[key_env])
            self.assertEqual(set(env) - {"PYTHONPATH", key_env}, set())

    def test_missing_key_omitted(self):
        self.assertEqual(run.family_env("glm", {}), {"PYTHONPATH": "src"})


class TestWorker(unittest.TestCase):
    def run_worker(self, family, csv_path, fresh=False, env=None):
        with mock.patch.object(run, "load_entries", return_value=[]), \
             mock.patch.object(run, "fetch_corpus", fake_corpus), \
             mock.patch.dict(os.environ, env or {}, clear=True), \
             mock.patch("tokencount.counters.count_tokens", return_value=7) as ct:
            rc = run.run_worker(family, fresh=fresh, results_csv=csv_path)
        return rc, ct

    def read_rows(self, csv_path):
        with open(csv_path, newline="") as f:
            return list(csv.DictReader(f))

    def test_appends_rows_with_exact_columns(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            rc, ct = self.run_worker("openai", csv_path, env={"OPENAI_API_KEY": "k"})
            self.assertEqual(rc, 0)
            self.assertEqual(ct.call_count, 4)
            rows = self.read_rows(csv_path)
            self.assertEqual(len(rows), 4)
            self.assertEqual(list(rows[0].keys()), run.CSV_COLUMNS)
            r = rows[0]
            self.assertTrue(r["file"].startswith("samples/"))
            self.assertEqual(
                (r["provider"], r["model"], r["strategy"], r["file"], r["file_type"],
                 r["sha256"], r["chars"], r["tokens"], r["note"]),
                ("openai", "gpt-6.2-astra", "openai_api", "samples/text/France",
                 "text", SAMPLE.sha256, "5", "7", ""),
            )

    def write_existing(self, csv_path):
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(run.CSV_COLUMNS)
            w.writerow(["2026-11-24T00:00:00+00:00", "openai", "gpt-6.2-astra", "openai_api",
                        "samples/text/France", "text", SAMPLE.sha256, "5", "7", ""])

    def test_dedup_skips_existing_pair(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            self.write_existing(csv_path)
            rc, ct = self.run_worker("openai", csv_path, env={"OPENAI_API_KEY": "k"})
            self.assertEqual(ct.call_count, 3)
            self.assertEqual(len(self.read_rows(csv_path)), 4)

    def test_fresh_recounts_everything(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            self.write_existing(csv_path)
            rc, ct = self.run_worker("openai", csv_path, fresh=True, env={"OPENAI_API_KEY": "k"})
            self.assertEqual(ct.call_count, 4)

    def test_error_note_row(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            with mock.patch.object(run, "load_entries", return_value=[]), \
                 mock.patch.object(run, "fetch_corpus", fake_corpus), \
                 mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True), \
                 mock.patch("tokencount.counters.count_tokens", side_effect=RuntimeError("boom")):
                run.run_worker("google", results_csv=csv_path)
            rows = self.read_rows(csv_path)
            self.assertEqual(len(rows), 3)
            for r in rows:
                self.assertEqual(r["tokens"], "")
                self.assertEqual(r["note"], "error: boom")

    def test_error_rows_are_recounted_on_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            with mock.patch.object(run, "load_entries", return_value=[]), \
                 mock.patch.object(run, "fetch_corpus", fake_corpus), \
                 mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True), \
                 mock.patch("tokencount.counters.count_tokens", side_effect=RuntimeError("boom")):
                run.run_worker("google", results_csv=csv_path)
            rc, ct = self.run_worker("google", csv_path, env={"GOOGLE_API_KEY": "k"})
            self.assertEqual(ct.call_count, 3)
            rows = self.read_rows(csv_path)
            self.assertEqual(len(rows), 6)
            self.assertEqual([r["tokens"] for r in rows[3:]], ["7", "7", "7"])
            rc, ct = self.run_worker("google", csv_path, env={"GOOGLE_API_KEY": "k"})
            self.assertEqual(ct.call_count, 0)
            self.assertEqual(len(self.read_rows(csv_path)), 6)

    def test_torn_trailing_row_is_not_a_dedup_key(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            with open(csv_path, "w", newline="") as f:
                f.write(",".join(run.CSV_COLUMNS) + "\n")
                f.write("2026-11-24T00:00:00+00:00,openai,gpt-6.2-astra,openai_api,"
                        "samples/text/France,text,%s,5,7,\n" % SAMPLE.sha256)
                f.write("2026-11-24T00:00:00+00:00,openai,gpt-6.2-sol")  # torn line, no newline
            keys = run.read_dedup_keys(csv_path)
            self.assertEqual(keys, {("gpt-6.2-astra", "openai_api", "samples/text/France", SAMPLE.sha256)})
            rc, ct = self.run_worker("openai", csv_path, env={"OPENAI_API_KEY": "k"})
            self.assertEqual(ct.call_count, 3)  # the torn row's model is recounted


class TestOrchestrator(unittest.TestCase):
    def test_dispatches_one_subprocess_per_family(self):
        with mock.patch.object(run, "resolve_secrets", return_value=ALL_SECRETS), \
             mock.patch.object(run, "load_entries", return_value=[]), \
             mock.patch.object(run, "fetch_corpus", fake_corpus), \
             mock.patch.object(run, "subprocess") as sp, \
             mock.patch.object(run, "render_results") as rr:
            rc = run.main([])
        self.assertEqual(rc, 0)
        self.assertEqual(sp.run.call_count, 5)
        families = []
        for call in sp.run.call_args_list:
            cmd = call.args[0]
            env = call.kwargs["env"]
            self.assertEqual(cmd[:3], [".venv-api/bin/python", "-m", "tokencount"])
            self.assertIn("--family", cmd)
            family = cmd[cmd.index("--family") + 1]
            families.append(family)
            self.assertEqual(set(env), {"PYTHONPATH", FAMILY_KEY[family]})
        self.assertEqual(sorted(families), sorted(FAMILY_KEY))
        rr.assert_called_once_with()

    def test_fresh_flag_propagates_to_workers_and_fetch(self):
        with mock.patch.object(run, "resolve_secrets", return_value={}), \
             mock.patch.object(run, "load_entries", return_value=[]), \
             mock.patch.object(run, "fetch_corpus", return_value=[SAMPLE]) as fc, \
             mock.patch.object(run, "subprocess") as sp, \
             mock.patch.object(run, "render_results"):
            run.main(["--fresh"])
        for call in sp.run.call_args_list:
            self.assertIn("--fresh", call.args[0])
        self.assertEqual(fc.call_args.kwargs.get("fresh"), True)

    def test_failed_worker_makes_main_nonzero_but_still_renders(self):
        with mock.patch.object(run, "resolve_secrets", return_value={}), \
             mock.patch.object(run, "load_entries", return_value=[]), \
             mock.patch.object(run, "fetch_corpus", fake_corpus), \
             mock.patch.object(run, "subprocess") as sp, \
             mock.patch.object(run, "render_results") as rr:
            sp.run.return_value = subprocess.CompletedProcess(args=[], returncode=1)
            rc = run.main([])
        self.assertEqual(rc, 1)
        rr.assert_called_once_with()


class TestSecretsGuard(unittest.TestCase):
    def test_provider_error_warns_and_continues(self):
        try:
            from secretspec.errors import SecretSpecError
        except ImportError:
            self.skipTest("secretspec SDK not installed; run in the base .venv")
        with mock.patch.object(run, "_resolve_with_secretspec", side_effect=SecretSpecError("sops not found")):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                secrets = run.resolve_secrets()
        self.assertEqual(secrets, {})
        self.assertIn("warning", err.getvalue().lower())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tokencount.run'`

- [ ] **Step 3: Implement `src/tokencount/run.py` and `src/tokencount/__main__.py`**

`run.py`: argparse with `--family` and `--fresh`; `CSV_COLUMNS` and `RESULTS_CSV = "results/results.csv"`; `route_env(family)` per Interfaces; `family_env(family, secrets)` per Interfaces; `_resolve_with_secretspec(path)` imports the secretspec SDK, resolves `secretspec.toml` (provider chain ["sops","env"], all keys required=false), calls `set_as_env()`, and reads the five declared names from `os.environ` into a dict; `resolve_secrets(path="secretspec.toml")` wraps it in try/except catching the SDK's `SecretSpecError` (`from secretspec.errors import SecretSpecError`; confirm the exact module path against the pinned 0.21.x wheel at implementation — `MissingRequiredError` cannot occur because every key is required=false), prints a warning on stderr, and returns `{}` on failure; `read_dedup_keys(csv_path)` returns the set of (model, strategy, file, sha256) already in the CSV, counting only rows with a numeric tokens value or note `n/a`/`missing key <ENV>` (`error:` rows are not deduped, so transient failures are retried on the next run) and skipping rows with a missing field (torn trailing line from a killed process); `append_row(csv_path, row)` writes the header when the file is new and otherwise appends the row with a single write call; `count_sample(model, sample, key)` returns `(tokens_str, note)` mapping MissingKeyError to `missing key <ENV>`, UnsupportedModelError to `n/a`, and any other exception to `error: <message>`; `run_worker(family, fresh=False, results_csv=None)` resolves `csv_path = results_csv or RESULTS_CSV`, lazily imports counters, loads samples via plan A's `fetch_corpus(load_entries(), fresh=fresh)`, and for each model in `models_for_family(family)` and each sample appends one row unless its dedup key exists and not fresh, returning 0; `render_results()` is the stub marked `# PLAN C HOOK: table.py implements this`; `main(argv=None)` returns `run_worker(...)` for `--family`, otherwise resolves secrets, fetches the corpus with `fetch_corpus(load_entries(), fresh=fresh)` from the repo root (default `dest_dir="samples"`, so `--fresh` both re-downloads and recounts), runs one `subprocess.run([f"{route_env(f)}/bin/python", "-m", "tokencount", "--family", f] (+ ["--fresh"]), env=family_env(f, secrets), check=False)` per family in `REGISTRY`, then calls `render_results()` and returns 0 only when every family subprocess exited 0 — a failed family (for example a fetch that raised) still renders the table but makes the whole run exit 1, so a partial run is never reported as success. `__main__.py` is:

```python
from tokencount.run import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/tokencount/run.py src/tokencount/__main__.py tests/test_run.py
git commit -m "feat: orchestrator and per-family worker with CSV results"
```

### Task 5: Offline partial run (no keys, sops absent)

**Files:**
- Modify: `tests/test_run.py` (append `TestOfflinePartialRun`)

**Interfaces:**
- Consumes: Task 4 `run.main`, `run.RESULTS_CSV`, plan A `fetch_corpus`, Task 2 `counters.TRANSPORT`.
- Produces: the pinned offline contract: with all five keys unset and no sops CLI, the worker writes `missing key <ENV>` rows for every API model and exits 0, with no HTTP attempted.

- [ ] **Step 1: Append the test** to `tests/test_run.py`:

```python
class TestOfflinePartialRun(unittest.TestCase):
    def test_missing_key_rows_and_exit_zero(self):
        def no_network(request):
            raise AssertionError("no HTTP call expected")
        counters.TRANSPORT = httpx.MockTransport(no_network)
        try:
            with tempfile.TemporaryDirectory() as d:
                csv_path = os.path.join(d, "results.csv")
                with mock.patch.object(run, "RESULTS_CSV", csv_path), \
                     mock.patch.object(run, "load_entries", return_value=[]), \
                     mock.patch.object(run, "fetch_corpus", fake_corpus), \
                     mock.patch.dict(os.environ, {}, clear=True):
                    rc = run.main(["--family", "glm"])
                self.assertEqual(rc, 0)
                with open(csv_path, newline="") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 3)
                for r in rows:
                    self.assertEqual(r["tokens"], "")
                    self.assertEqual(r["note"], "missing key Z_AI_API_KEY")
        finally:
            counters.TRANSPORT = None
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`
Expected: PASS. Task 4 already implements the missing-key path, so this test passes immediately; it pins the offline contract. If it fails, fix `count_sample` in `run.py`, not the test.

- [ ] **Step 3: Implement**

No new code expected. The guard in `resolve_secrets` (Task 4) plus the MissingKeyError path in `count_sample` cover the sops-absent case.

- [ ] **Step 4: Run the full suite to verify**

Run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run tests.test_models -v` and `PYTHONPATH=src .venv-api/bin/python -m unittest tests.test_counters -v`
Expected: PASS in both envs (live classes in test_counters skipped without keys)

- [ ] **Step 5: Commit**

```bash
git add tests/test_run.py
git commit -m "test: offline partial run writes missing key rows and exits 0"
```

## Verification and validation

Success criteria: from the repo root, `PYTHONPATH=src .venv/bin/python -m unittest tests.test_models tests.test_run -v` and `PYTHONPATH=src .venv-api/bin/python -m unittest tests.test_counters -v` pass (the live classes in test_counters run only when the matching key is present); with all five keys unset and sops absent, the run exits 0 with `missing key <ENV>` rows and no HTTP attempted; a rerun over an unchanged corpus adds zero deduped rows while `error:` rows and torn trailing lines are recounted; a failed family worker makes the orchestrator exit 1 while still rendering the table.

- Unit (Task 2, `.venv-api`): mock-transport tests pin per strategy the route, auth header, request body, response field (including Kimi `data.total_tokens`), baseline subtraction (probe minus 1), 429 retry, 400/404 → `n/a`, and the missing-key error.
- Live (Task 3, key-gated): per-endpoint counts against the real APIs; the OpenAI count must equal the tiktoken o200k_base vector for the same string and a 1-char input must count as exactly 1 (proving the zero wrapper), and each message-based strategy must return 1 for a 1-char input with constant deltas across 1/2/3-char inputs.
- Secrets: `TestSecretsGuard` proves a `SecretSpecError` (missing sops CLI, undecryptable `secrets.enc.yaml`) warns and yields `{}` — never a silent abort; plan A's `TestSecretspecSdk` validates the manifest and the nested `[project][profile][key]` ciphertext layout that the `sops://` provider reads.
- Dedup/resume: numeric and `n/a`/`missing key` rows dedup; `error:` rows and malformed trailing lines do not; `--fresh` propagates to both the orchestrator's `fetch_corpus` call and every worker.
- Cross-plan: CSV `file` values are the relative `samples/<file_type>/<name>` strings (repo-root CWD, `dest_dir="samples"`); `chars` is decoded characters and `sha256` is over raw bytes; a fetch failure aborts before any CSV row is written (plan A contract), so `results/results.csv` and the `samples/` cache never disagree mid-run.

## Handoff

- Plan saved at `docs/superpowers/plans/2026-11-24-plan-b-api-counting-pathway.md`.
- Depends on plan A: `.venv` and `.venv-api`, `src/tokencount/corpus.py`, `corpus/eu-members.txt`, `corpus/repos.txt`, `secretspec.toml`, `secrets.enc.yaml`, and `.sops.yaml` must be merged first.
- Awaits owner review and the execution-method choice (subagent-driven or native) before implementation.
