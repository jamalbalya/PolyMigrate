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

    def test_provider_timeouts_must_be_finite_positive_numbers(self):
        for timeout in (float("nan"), float("inf"), float("-inf"), True, 0):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "finite positive number"):
                OpenAICompatibleProvider("router", "key", "model", timeout=timeout)

    def test_output_token_limits_must_be_integers_not_booleans(self):
        for limit in (1.5, True, 0, 16_385):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "integer between 1 and 16384"):
                GeminiProvider("key", "model", max_output_tokens=limit)

    def test_anthropic_rejects_whitespace_only_model_id(self):
        with self.assertRaisesRegex(ValueError, "api_key and model_id are required"):
            AnthropicProvider("key", "   ")

    def test_https_base_url_is_accepted(self):
        _validate_base_url("https://example.com/v1")


    def test_invalid_port_is_rejected_as_configuration_error(self):
        with self.assertRaisesRegex(ValueError, "valid URL with a valid port"):
            _validate_base_url("https://example.com:not-a-port/v1")

    def test_credentials_in_base_url_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not embed credentials"):
            _validate_base_url("https://user:password@example.com/v1")

    def test_query_and_fragment_in_base_url_are_rejected(self):
        for url in ("https://example.com/v1?api_key=secret", "https://example.com/v1#fragment"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "query string or fragment"):
                _validate_base_url(url)

    def test_malformed_ipv6_base_url_is_rejected_cleanly(self):
        with self.assertRaisesRegex(ValueError, "valid URL with a valid port"):
            _validate_base_url("https://[not-an-ipv6-address]/v1")

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

    def test_model_discovery_http_error_is_sanitized(self):
        error = urllib.error.HTTPError("http://localhost:20128/v1/models", 401, "unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            provider = OpenAICompatibleProvider("9router", "super-secret-token", "",
                                                base_url="http://localhost:20128/v1")
            with self.assertRaises(ProviderRequestError) as captured:
                provider.list_models()
        self.assertIn("HTTP 401", str(captured.exception))
        self.assertNotIn("super-secret-token", str(captured.exception))

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


    def test_openai_compatible_success_contract_and_structured_output(self):
        response = BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"content":"{\\"answer\\":42}"}}]}')
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            provider = OpenAICompatibleProvider("openai", "test-key", "gpt-test",
                                                base_url="https://api.example.test/v1")
            result = provider.generate(ModelRequest("test-task", "return JSON", {}, require_structured_output=True))
        request = urlopen.call_args.args[0]
        payload = __import__("json").loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.example.test/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(payload["model"], "gpt-test")
        self.assertEqual(payload["max_completion_tokens"], 8192)
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(result.structured, {"answer": 42})

    def test_anthropic_messages_request_and_response_contract(self):
        response = BytesIO(b'{"stop_reason":"end_turn","content":[{"type":"text","text":"migration plan"}]}')
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            provider = AnthropicProvider("test-key", "claude-test", base_url="https://api.example.test/v1")
            result = provider.generate(ModelRequest("test-task", "make a plan", {}))
        request = urlopen.call_args.args[0]
        payload = __import__("json").loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.example.test/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "test-key")
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(payload["model"], "claude-test")
        self.assertEqual(payload["max_tokens"], 8192)
        self.assertEqual(result.content, "migration plan")

    def test_gemini_generate_content_structured_request_contract(self):
        response = BytesIO(b'{"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":"{\\"ok\\":true}"}]}}]}')
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            provider = GeminiProvider("test-key", "model with/slash", base_url="https://api.example.test/v1beta")
            result = provider.generate(ModelRequest("test-task", "return JSON", {}, require_structured_output=True))
        request = urlopen.call_args.args[0]
        payload = __import__("json").loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.example.test/v1beta/models/model%20with%2Fslash:generateContent")
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 8192)
        self.assertEqual(result.structured, {"ok": True})

    def test_openai_truncated_response_is_rejected(self):
        response = BytesIO(b'{"choices":[{"finish_reason":"length","message":{"content":"partial"}}]}')
        with patch("urllib.request.urlopen", return_value=response):
            provider = OpenAICompatibleProvider("openai", "test-key", "gpt-test",
                                                base_url="https://api.example.test/v1")
            with self.assertRaisesRegex(ProviderRequestError, "truncated"):
                provider.generate(ModelRequest("test-task", "prompt", {}))


if __name__ == "__main__":
    unittest.main()
