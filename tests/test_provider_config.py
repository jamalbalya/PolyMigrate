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

    def test_9router_uses_local_openai_compatible_endpoint(self):
        registry, warnings = build_provider_registry({
            "POLYMIGRATE_9ROUTER_API_KEY": "not-a-real-secret",
            "POLYMIGRATE_9ROUTER_MODEL": "test-model",
        })
        provider = registry.get("9router")
        self.assertEqual(provider.base_url, "http://localhost:20128/v1")
        self.assertEqual(provider.model_id, "test-model")
        self.assertEqual(warnings, ())

    def test_9router_endpoint_can_be_overridden(self):
        registry, warnings = build_provider_registry({
            "POLYMIGRATE_9ROUTER_API_KEY": "not-a-real-secret",
            "POLYMIGRATE_9ROUTER_MODEL": "test-model",
            "POLYMIGRATE_9ROUTER_BASE_URL": "http://127.0.0.1:20128/v1",
            "POLYMIGRATE_9ROUTER_MAX_OUTPUT_TOKENS": "2048",
        })
        provider = registry.get("9router")
        self.assertEqual(provider.base_url, "http://127.0.0.1:20128/v1")
        self.assertEqual(provider.max_output_tokens, 2048)
        self.assertEqual(warnings, ())

    def test_output_token_budget_is_configurable_and_bounded(self):
        registry, warnings = build_provider_registry({
            "OPENAI_API_KEY": "not-a-real-secret",
            "OPENAI_MODEL": "test-model",
            "OPENAI_MAX_OUTPUT_TOKENS": "2048",
        })
        self.assertEqual(registry.get("openai").max_output_tokens, 2048)
        self.assertEqual(warnings, ())

    def test_invalid_output_token_budget_uses_safe_default_without_secret_logging(self):
        registry, warnings = build_provider_registry({
            "OPENAI_API_KEY": "not-a-real-secret",
            "OPENAI_MODEL": "test-model",
            "OPENAI_MAX_OUTPUT_TOKENS": "999999",
        })
        self.assertEqual(registry.get("openai").max_output_tokens, 8192)
        self.assertTrue(any("OPENAI_MAX_OUTPUT_TOKENS" in warning for warning in warnings))
        self.assertNotIn("not-a-real-secret", " ".join(warnings))


if __name__ == "__main__":
    unittest.main()
