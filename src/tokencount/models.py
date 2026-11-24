from dataclasses import dataclass


@dataclass
class Model:
    provider: str
    model: str
    family: str
    strategy: str
    key_env: str
    tokenizer_file: str | None = None


# family -> (strategy, key env, model ids); plan C appends hf_local rows here as data
_FAMILIES = {
    "openai": (
        "openai_api",
        "OPENAI_API_KEY",
        ["gpt-6.2-astra", "gpt-6.2-sol", "gpt-6.1-terra", "gpt-6.1-luna"],
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
    "glm": ("zai_api", "Z_AI_API_KEY", ["glm-5.4", "glm-5.3", "glm-5.3-flash"]),
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


def models_for_family(family: str) -> list[Model]:
    return [m for m in REGISTRY if m.family == family]
