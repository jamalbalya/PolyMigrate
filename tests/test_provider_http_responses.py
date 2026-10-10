"""Provider response parsing tests with mocked HTTP responses."""
import json
import unittest
from unittest.mock import patch

from polymigrate.ai.http_providers import AnthropicProvider, GeminiProvider, OpenAICompatibleProvider, ProviderRequestError
from polymigrate.ai.protocols import ModelRequest


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit=-1): return self.payload if limit < 0 else self.payload[:limit]


class ProviderResponseTests(unittest.TestCase):
    def test_openai_compatible_structured_json_response(self):
        response=FakeHTTPResponse({"choices":[{"message":{"content":'{"choice":"ok"}'}}]})
        with patch("urllib.request.urlopen",return_value=response) as open_url:
            result=OpenAICompatibleProvider("openai","fake-key","test-model").generate(
                ModelRequest("decision","return json",{},require_structured_output=True))
        request = open_url.call_args.args[0]
        request_payload=json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-key")
        self.assertEqual(request_payload["max_completion_tokens"],8192)
        self.assertEqual(request_payload["response_format"], {"type": "json_object"})
        self.assertEqual(result.structured_data,{"choice":"ok"})
        self.assertEqual(result.provider_id,"openai")

    def test_anthropic_text_response(self):
        response=FakeHTTPResponse({"content":[{"type":"text","text":"translated"}]})
        with patch("urllib.request.urlopen",return_value=response) as open_url:
            result=AnthropicProvider("fake-key","test-model").generate(ModelRequest("translate","prompt",{}))
        request = open_url.call_args.args[0]
        request_payload=json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.get_header("X-api-key"), "fake-key")
        self.assertEqual(request.get_header("Anthropic-version"), "2023-06-01")
        self.assertEqual(request_payload["max_tokens"], 8192)
        self.assertEqual(request_payload["messages"], [{"role": "user", "content": "Task: translate\\nContext JSON:\n{}\\n\\nInstructions:\nprompt"}])
        self.assertEqual(result.content,"translated")

    def test_gemini_text_response(self):
        response=FakeHTTPResponse({"candidates":[{"content":{"parts":[{"text":"translated"}]}}]})
        with patch("urllib.request.urlopen",return_value=response) as open_url:
            result=GeminiProvider("fake-key","test-model").generate(ModelRequest("translate","prompt",{}))
        request = open_url.call_args.args[0]
        request_payload=json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent")
        self.assertEqual(request.get_header("X-goog-api-key"), "fake-key")
        self.assertEqual(request_payload["generationConfig"]["maxOutputTokens"], 8192)
        self.assertEqual(request_payload["contents"], [{"role": "user", "parts": [{"text": "Task: translate\\nContext JSON:\n{}\\n\\nInstructions:\nprompt"}]}])
        self.assertEqual(result.content,"translated")

    def test_gemini_structured_output_uses_json_response_mime_type(self):
        response=FakeHTTPResponse({"candidates":[{"content":{"parts":[{"text":'{"ok":true}'}]}}]})
        with patch("urllib.request.urlopen",return_value=response) as open_url:
            result=GeminiProvider("fake-key","test-model").generate(
                ModelRequest("decision","return json",{},require_structured_output=True))
        request_payload=json.loads(open_url.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(result.structured_data, {"ok": True})

    def test_openai_structured_mode_rejects_non_json_text(self):
        response=FakeHTTPResponse({"choices":[{"message":{"content":"not json"}}]})
        with patch("urllib.request.urlopen",return_value=response):
            with self.assertRaisesRegex(ProviderRequestError,"valid JSON object"):
                OpenAICompatibleProvider("openai","fake-key","test-model").generate(
                    ModelRequest("decision","return json",{},require_structured_output=True))

    def test_oversized_provider_response_is_rejected(self):
        response=FakeHTTPResponse(b" " * 2_000_001)
        with patch("urllib.request.urlopen",return_value=response):
            with self.assertRaisesRegex(ProviderRequestError,"2 MB safety limit"):
                OpenAICompatibleProvider("openai","fake-key","test-model").generate(ModelRequest("translate","prompt",{}))


if __name__ == "__main__":
    unittest.main()
