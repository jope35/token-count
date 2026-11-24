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
