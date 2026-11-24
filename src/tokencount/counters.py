import json
import time
from typing import Optional

import httpx
from tenacity import Retrying, stop_after_attempt, wait_fixed, retry_if_exception, retry_if_exception_type

STRATEGY_KEY_ENV = {
    "openai_api": "OPENAI_API_KEY",
    "anthropic_api": "ANTHROPIC_API_KEY",
    "google_api": "GOOGLE_API_KEY",
    "zai_api": "Z_AI_API_KEY",
    "kimi_api": "MOONSHOT_API_KEY",
}

TRANSPORT = None
RETRY_WAIT_SECONDS = 1
CALL_DELAY_SECONDS = 0.1
_BASELINE_CACHE = {}

class MissingKeyError(Exception):
    def __init__(self, env: str):
        self.env = env
        super().__init__(f"Missing key for {env}")

class UnsupportedModelError(Exception):
    pass

def _post_json(url: str, *, headers: dict, payload: dict, params: dict = None) -> dict:
    retrying = Retrying(
        stop=stop_after_attempt(3),
        wait=wait_fixed(RETRY_WAIT_SECONDS),
        retry=retry_if_exception(lambda e: isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429) | retry_if_exception_type(httpx.HTTPStatusError),
    )
    
    with httpx.Client(transport=TRANSPORT) as client:
        for attempt in retrying:
            with attempt:
                response = client.post(url, headers=headers, json=payload, params=params)
                if response.status_code in (400, 404):
                    raise UnsupportedModelError(response.json())
                response.raise_for_status()
                time.sleep(CALL_DELAY_SECONDS)
                return response.json()

def _count_openai_api(model_id: str, text: str, key: str) -> int:
    url = "https://api.openai.com/v1/responses/input_tokens"
    headers = {"Authorization": f"Bearer {key}"}
    payload = {"model": model_id, "input": text}
    response = _post_json(url, headers=headers, payload=payload, params={"key": key})
    return response["input_tokens"]

def _count_anthropic_api(model_id: str, text: str, key: str) -> int:
    url = "https://api.anthropic.com/v1/messages/count_tokens"
    headers = {
        "anthropic-version": "2026-10-21",
        "x-api-key": key,
    }
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": text}],
    }
    response = _post_json(url, headers=headers, payload=payload, params={"key": key})
    return response["input_tokens"]

def _count_google_api(model_id: str, text: str, key: str) -> int:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:countTokens"
    headers = {}
    payload = {"prompt": {"text": text}}
    response = _post_json(url, headers=headers, payload=payload, params={"key": key})
    return response["totalTokens"]

def _count_zai_api(model_id: str, text: str, key: str) -> int:
    url = "https://api.z.ai/api/paas/v4/tokenizer"
    headers = {"Authorization": f"Bearer {key}"}
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": text}],
    }
    response = _post_json(url, headers=headers, payload=payload)
    return response["usage"]["prompt_tokens"]

def _count_kimi_api(model_id: str, text: str, key: str) -> int:
    url = "https://api.moonshot.ai/v1/tokenizers/estimate-token-count"
    headers = {"Authorization": f"Bearer {key}"}
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": text}],
    }
    response = _post_json(url, headers=headers, payload=payload)
    return response["data"]["total_tokens"]

def baseline_tokens(strategy: str, model_id: str, key: str) -> int:
    if strategy in ("openai_api", "google_api"):
        return 0
    cache_key = (strategy, model_id)
    if cache_key in _BASELINE_CACHE:
        return _BASELINE_CACHE[cache_key]
    
    if strategy == "anthropic_api":
        raw = _count_anthropic_api(model_id, "x", key)
    elif strategy == "zai_api":
        raw = _count_zai_api(model_id, "x", key)
    elif strategy == "kimi_api":
        raw = _count_kimi_api(model_id, "x", key)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
    
    baseline = raw - 1
    _BASELINE_CACHE[cache_key] = baseline
    return baseline

def count_tokens(
    strategy: str, model_id: str, text: str, key: Optional[str] = None, tokenizer_file: Optional[str] = None
) -> int:
    if strategy == "hf_local":
        raise ValueError("hf_local is not supported in this task")

    if key is None:
        raise MissingKeyError(STRATEGY_KEY_ENV[strategy])

    baseline = baseline_tokens(strategy, model_id, key)
    if strategy == "openai_api":
        raw = _count_openai_api(model_id, text, key)
    elif strategy == "anthropic_api":
        raw = _count_anthropic_api(model_id, text, key)
    elif strategy == "google_api":
        raw = _count_google_api(model_id, text, key)
    elif strategy == "zai_api":
        raw = _count_zai_api(model_id, text, key)
    elif strategy == "kimi_api":
        raw = _count_kimi_api(model_id, text, key)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    return raw - baseline
