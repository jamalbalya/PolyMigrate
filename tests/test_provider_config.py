"""Provider configuration tests; no live provider calls are made."""
import unittest

from polymigrate.ai.config import build_provider_registry
from polymigrate.ai.registry import ProviderUnavailableError


class ProviderConfigTests(unittest.TestCase):
    def test_empty_environment_configures_no_providers(self):
        registry, warnings = build_provider_registry({})
        self.assertEqual(warnings, ())
        with self.assertRaises(ProviderUnavailableError):
            registry.get("openai")

    def test_provider_is_registered_only_with_key_and_model(self):
        registry, warnings = build_provider_registry({
            "OPENAI_API_KEY": "not-a-real-secret",
            "OPENAI_MODEL": "test-model",
        })
        self.assertEqual(warnings, ())
        self.assertEqual(registry.get("openai").provider_id, "openai")

    def test_missing_model_produces_non_secret_warning(self):
        registry, warnings = build_provider_registry({"OPENAI_API_KEY": "not-a-real-secret"})
        self.assertEqual(len(warnings), 1)
        self.assertIn("OPENAI_MODEL", warnings[0])
        self.assertNotIn("not-a-real-secret", " ".join(warnings))
        with self.assertRaises(ProviderUnavailableError):
            registry.get("openai")

    def test_openrouter_uses_compatible_adapter(self):
        registry, warnings = build_provider_registry({
            "OPENROUTER_API_KEY": "not-a-real-secret",
            "OPENROUTER_MODEL": "vendor/model",
        })
        self.assertEqual(warnings, ())
        provider = registry.get("openrouter")
        self.assertEqual(provider.base_url, "https://openrouter.ai/api/v1")


if __name__ == "__main__":
    unittest.main()
