"""Security tests for data passed to providers and returned from agent tools."""
import json
import unittest

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.agent.runtime import AgentRuntime
from polymigrate.agent.tools import ToolRegistry
from polymigrate.security.redaction import redact_payload, redact_text


class CapturingProvider:
    provider_id = "capture"
    def __init__(self, response):
        self.response = response
        self.requests = []
    def get_capabilities(self):
        return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        self.requests.append(request)
        return ModelResponse(self.response, "capture", "test")


class RedactionTests(unittest.TestCase):
    def test_sensitive_mapping_fields_are_redacted(self):
        self.assertEqual(redact_payload({"api_key": "secret-value"})["api_key"], "[REDACTED]")

    def test_common_token_patterns_are_redacted(self):
        value = redact_text("Authorization: Bearer abc.def.ghi and sk-12345678901234567890")
        self.assertNotIn("abc.def.ghi", value)
        self.assertNotIn("sk-12345678901234567890", value)

    def test_agent_redacts_context_and_task_before_provider_call(self):
        provider = CapturingProvider(json.dumps({"action": "final", "result": {"summary": "done"}}))
        registry = ProviderRegistry()
        registry.register(provider)
        runtime = AgentRuntime(registry, ToolRegistry(), max_steps=1)
        result = runtime.run("capture", "process password=top-secret", {
            "api_key": "sensitive-value",
            "notes": "Authorization: Bearer bearer-secret",
        })
        prompt = provider.requests[0].prompt
        self.assertNotIn("sensitive-value", prompt)
        self.assertNotIn("bearer-secret", prompt)
        self.assertNotIn("top-secret", prompt)
        self.assertEqual(result.status, "SUCCESS")


if __name__ == "__main__":
    unittest.main()
