from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Model:
    provider: str
    model: str
    family: str
    strategy: str
    key_env: str
    tokenizer_file: Optional[str] = None

REGISTRY: List[Model] = [
    # OpenAI models
    Model(
        provider="openai",
        model="gpt-6.2-astra",
        family="openai",
        strategy="openai_api",
        key_env="OPENAI_API_KEY",
    ),
    Model(
        provider="openai",
        model="gpt-6.2-sol",
        family="openai",
        strategy="openai_api",
        key_env="OPENAI_API_KEY",
    ),
    Model(
        provider="openai",
        model="gpt-6.1-terra",
        family="openai",
        strategy="openai_api",
        key_env="OPENAI_API_KEY",
    ),
    Model(
        provider="openai",
        model="gpt-6.1-luna",
        family="openai",
        strategy="openai_api",
        key_env="OPENAI_API_KEY",
    ),
    # Anthropic models
    Model(
        provider="anthropic",
        model="claude-fable-5-2",
        family="anthropic",
        strategy="anthropic_api",
        key_env="ANTHROPIC_API_KEY",
    ),
    Model(
        provider="anthropic",
        model="claude-opus-5-5",
        family="anthropic",
        strategy="anthropic_api",
        key_env="ANTHROPIC_API_KEY",
    ),
    Model(
        provider="anthropic",
        model="claude-sonnet-5-5",
        family="anthropic",
        strategy="anthropic_api",
        key_env="ANTHROPIC_API_KEY",
    ),
    Model(
        provider="anthropic",
        model="claude-haiku-5-5",
        family="anthropic",
        strategy="anthropic_api",
        key_env="ANTHROPIC_API_KEY",
    ),
    # Google models
    Model(
        provider="google",
        model="gemini-4-neon",
        family="google",
        strategy="google_api",
        key_env="GOOGLE_API_KEY",
    ),
    Model(
        provider="google",
        model="gemini-4-hydrogen",
        family="google",
        strategy="google_api",
        key_env="GOOGLE_API_KEY",
    ),
    Model(
        provider="google",
        model="gemini-4-carbon",
        family="google",
        strategy="google_api",
        key_env="GOOGLE_API_KEY",
    ),
    # GLM models
    Model(
        provider="glm",
        model="glm-5.4",
        family="glm",
        strategy="zai_api",
        key_env="Z_AI_API_KEY",
    ),
    Model(
        provider="glm",
        model="glm-5.3",
        family="glm",
        strategy="zai_api",
        key_env="Z_AI_API_KEY",
    ),
    Model(
        provider="glm",
        model="glm-5.3-flash",
        family="glm",
        strategy="zai_api",
        key_env="Z_AI_API_KEY",
    ),
    # Kimi models
    Model(
        provider="kimi",
        model="kimi-k3.1-pro",
        family="kimi",
        strategy="kimi_api",
        key_env="MOONSHOT_API_KEY",
    ),
    Model(
        provider="kimi",
        model="kimi-k3",
        family="kimi",
        strategy="kimi_api",
        key_env="MOONSHOT_API_KEY",
    ),
    Model(
        provider="kimi",
        model="kimi-k2.7-code",
        family="kimi",
        strategy="kimi_api",
        key_env="MOONSHOT_API_KEY",
    ),
    Model(
        provider="kimi",
        model="kimi-k2.6",
        family="kimi",
        strategy="kimi_api",
        key_env="MOONSHOT_API_KEY",
    ),
]

def models_for_family(family: str) -> List[Model]:
    return [m for m in REGISTRY if m.family == family]