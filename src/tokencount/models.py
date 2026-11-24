from dataclasses import dataclass


@dataclass
class Model:
    provider: str
    model: str
    family: str
    strategy: str
    key_env: str | None
    tokenizer_file: str | None = None


# family -> (strategy, key env, model ids); plan C appends hf_local rows here as data
_FAMILIES = {
    "openai": (
        "openai_api",
        "OPENAI_API_KEY",
        ["gpt-6.2-astra", "gpt-6.2-sol", "gpt-6.1-terra", "gpt-6-luna"],
    ),
    "anthropic": (
        "anthropic_api",
        "ANTHROPIC_API_KEY",
        [
            "claude-fable-5-2",
            "claude-opus-5-5",
            "claude-sonnet-5-5",
            "claude-haiku-5-5",
        ],
    ),
    "google": (
        "google_api",
        "GOOGLE_API_KEY",
        ["gemini-4-neon", "gemini-4-hydrogen", "gemini-4-carbon"],
    ),
    "glm": ("zai_api", "Z_AI_API_KEY", ["glm-5.4"]),
    "kimi": (
        "kimi_api",
        "MOONSHOT_API_KEY",
        ["kimi-k3.1-pro", "kimi-k3", "kimi-k2.7-code", "kimi-k2.6"],
    ),
}

REGISTRY = [
    Model(
        provider=family, model=model, family=family, strategy=strategy, key_env=key_env
    )
    for family, (strategy, key_env, models) in _FAMILIES.items()
    for model in models
]

# plan C: local families, counted offline from the vendored tokenizer files
REGISTRY += [
    Model(
        provider="deepseek",
        model="deepseek-flash",
        family="deepseek",
        strategy="hf_local",
        key_env=None,
        tokenizer_file="tokenizers/deepseek-flash.json",
    ),
    Model(
        provider="deepseek",
        model="deepseek-v4-pro",
        family="deepseek",
        strategy="hf_local",
        key_env=None,
        tokenizer_file="tokenizers/deepseek-v4-pro.json",
    ),
    Model(
        provider="mistral",
        model="mistral-large-4",
        family="mistral",
        strategy="hf_local",
        key_env=None,
        tokenizer_file="tokenizers/mistral-large-4.json",
    ),
    Model(
        provider="mistral",
        model="mistral-small-2603",
        family="mistral",
        strategy="hf_local",
        key_env=None,
        tokenizer_file="tokenizers/mistral-small-2603.json",
    ),
    Model(
        provider="mistral",
        model="mistral-medium-3-5",
        family="mistral",
        strategy="hf_local",
        key_env=None,
        tokenizer_file="tokenizers/mistral-medium-3-5.json",
    ),
    Model(
        provider="glm",
        model="glm-5.3",
        family="glm_local",
        strategy="hf_local",
        key_env=None,
        tokenizer_file="tokenizers/glm-5.3.json",
    ),
    Model(
        provider="glm",
        model="glm-5.3-flash",
        family="glm_local",
        strategy="hf_local",
        key_env=None,
        tokenizer_file="tokenizers/glm-5.3-flash.json",
    ),
    Model(
        provider="kimi",
        model="kimi-k3.1-pro-local",
        family="kimi_local",
        strategy="kimi_local",
        key_env=None,
        tokenizer_file="tokenizers/kimi-k3.1-pro",
    ),
    Model(
        provider="kimi",
        model="kimi-k3-local",
        family="kimi_local",
        strategy="kimi_local",
        key_env=None,
        tokenizer_file="tokenizers/kimi-k3",
    ),
    Model(
        provider="kimi",
        model="kimi-k2.7-code-local",
        family="kimi_local",
        strategy="kimi_local",
        key_env=None,
        tokenizer_file="tokenizers/kimi-k2.7-code",
    ),
    Model(
        provider="kimi",
        model="kimi-k2.6-local",
        family="kimi_local",
        strategy="kimi_local",
        key_env=None,
        tokenizer_file="tokenizers/kimi-k2.6",
    ),
]


def models_for_family(family: str) -> list[Model]:
    return [m for m in REGISTRY if m.family == family]
