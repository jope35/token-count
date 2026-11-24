import unittest

from tokencount.models import REGISTRY, models_for_family

EXPECTED = {
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
KNOWN_STRATEGIES = {
    "openai_api",
    "anthropic_api",
    "google_api",
    "zai_api",
    "kimi_api",
    "hf_local",
}


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
