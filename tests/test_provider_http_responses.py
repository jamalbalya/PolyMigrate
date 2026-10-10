"""Provider response parsing tests with mocked HTTP responses."""
import json
import unittest
from unittest.mock import patch

from polymigrate.ai.http_providers import AnthropicProvider, GeminiProvider, OpenAICompatibleProvider, ProviderRequestError
from polymigrate.ai.protocols import ModelRequest


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit=-1): return self.payload if limit < 0 else self.payload[:limit]


class ProviderResponseTests(unittest.TestCase):
    def test_openai_compatible_structured_json_response(self):
        response=FakeHTTPResponse({"choices":[{"message":{"content":'{"choice":"ok"}'}}]})
        with patch("urllib.request.urlopen",return_value=response) as open_url:
            result=OpenAICompatibleProvider("openai","fake-key","test-model").generate(
                ModelRequest("decision","return json",{},require_structured_output=True))
        request_payload=json.loads(open_url.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(request_payload["max_completion_tokens"],8192)
        self.assertEqual(result.structured_data,{"choice":"ok"})
        self.assertEqual(result.provider_id,"openai")

    def test_anthropic_text_response(self):
        response=FakeHTTPResponse({"content":[{"type":"text","text":"translated"}]})
        with patch("urllib.request.urlopen",return_value=response):
            result=AnthropicProvider("fake-key","test-model").generate(ModelRequest("translate","prompt",{}))
        self.assertEqual(result.content,"translated")

    def test_gemini_text_response(self):
        response=FakeHTTPResponse({"candidates":[{"content":{"parts":[{"text":"translated"}]}}]})
        with patch("urllib.request.urlopen",return_value=response):
            result=GeminiProvider("fake-key","test-model").generate(ModelRequest("translate","prompt",{}))
        self.assertEqual(result.content,"translated")

    def test_openai_structured_mode_rejects_non_json_text(self):
        response=FakeHTTPResponse({"choices":[{"message":{"content":"not json"}}]})
        with patch("urllib.request.urlopen",return_value=response):
            with self.assertRaisesRegex(ProviderRequestError,"valid JSON object"):
                OpenAICompatibleProvider("openai","fake-key","test-model").generate(
                    ModelRequest("decision","return json",{},require_structured_output=True))


if __name__ == "__main__":
    unittest.main()
