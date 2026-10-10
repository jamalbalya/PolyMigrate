"""Provider adapter contract tests; no live network or credentials are used."""
import unittest
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
