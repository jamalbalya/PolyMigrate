"""Provider adapter contract tests; no live network or credentials are used."""
import unittest
from io import BytesIO
from unittest.mock import patch
import urllib.error

from polymigrate.ai.http_providers import (
    AnthropicProvider, GeminiProvider, OpenAICompatibleProvider,
    ProviderRequestError, _validate_base_url,
)
from polymigrate.ai.protocols import ModelRequest


class ProviderAdapterTests(unittest.TestCase):
    def test_https_base_url_is_accepted(self):
        _validate_base_url("https://example.com/v1")

    def test_plain_http_non_loopback_is_rejected(self):
        with self.assertRaises(ValueError):
            _validate_base_url("http://example.com/v1")

    def test_loopback_http_is_allowed_for_local_test_servers(self):
        _validate_base_url("http://127.0.0.1:8080/v1")

    def test_openai_compatible_model_discovery_uses_authenticated_get(self):
        response = BytesIO(b'{"data":[{"id":"model-z"},{"id":"model-a"},{"id":"model-a"}]}')
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            provider = OpenAICompatibleProvider("9router", "not-a-real-secret", "model",
                                                base_url="http://localhost:20128/v1")
            models = provider.list_models()
        self.assertEqual(models, ("model-a", "model-z"))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "GET")
        self.assertEqual(request.full_url, "http://localhost:20128/v1/models")
        self.assertEqual(request.get_header("Authorization"), "Bearer not-a-real-secret")

    def test_model_discovery_provider_can_exist_without_generation_model(self):
        provider = OpenAICompatibleProvider("9router", "not-a-real-secret", "",
                                            base_url="http://localhost:20128/v1")
        response = BytesIO(b'{"data":[{"id":"chatgpt-model"}]}')
        with patch("urllib.request.urlopen", return_value=response):
            self.assertEqual(provider.list_models(), ("chatgpt-model",))

    def test_generation_is_rejected_when_model_is_unset(self):
        provider = OpenAICompatibleProvider("9router", "not-a-real-secret", "",
                                            base_url="http://localhost:20128/v1")
        with patch("urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(ProviderRequestError, "model is not configured"):
                provider.generate(ModelRequest("test", "prompt", {}))
        urlopen.assert_not_called()

    def test_provider_capabilities_do_not_claim_tool_calling(self):
        self.assertFalse(OpenAICompatibleProvider("router", "dummy-key", "model").get_capabilities().tool_calling)
        self.assertFalse(AnthropicProvider("dummy-key", "model").get_capabilities().tool_calling)
        self.assertFalse(GeminiProvider("dummy-key", "model").get_capabilities().tool_calling)

    def test_provider_http_error_does_not_echo_credentials(self):
        error = urllib.error.HTTPError("https://example.com", 401, "unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            provider = OpenAICompatibleProvider("router", "super-secret-token", "model",
                                                base_url="https://example.com/v1")
            with self.assertRaises(ProviderRequestError) as captured:
                provider.generate(ModelRequest("test", "prompt", {}))
        self.assertNotIn("super-secret-token", str(captured.exception))
        self.assertIn("HTTP 401", str(captured.exception))


if __name__ == "__main__":
    unittest.main()
