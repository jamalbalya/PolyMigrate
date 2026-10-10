"""Tests for the provider diagnostics command."""
import unittest
from io import StringIO
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from polymigrate.cli import main
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities


class ProviderCLITests(unittest.TestCase):
    def test_live_check_sends_only_a_source_free_health_request(self):
        class FakeProvider:
            provider_id = "fake"
            model_id = "fake-model"
            def __init__(self):
                self.requests = []
            def get_capabilities(self):
                return ProviderCapabilities(structured_output=True)
            def generate(self, request):
                self.requests.append(request)
                return ModelResponse('{"status":"ok"}', self.provider_id, self.model_id,
                                     {"status": "ok"})

        provider = FakeProvider()
        registry = ProviderRegistry()
        registry.register(provider)
        stdout, stderr = StringIO(), StringIO()
        with patch("polymigrate.cli.build_provider_registry", return_value=(registry, ())), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["providers", "--check"])
        self.assertEqual(result, 0, stderr.getvalue())
        self.assertIn("connectivity: PASS", stdout.getvalue())
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0].task, "provider_connectivity_check")
        self.assertNotIn("source", provider.requests[0].context)
        self.assertEqual(stderr.getvalue(), "")

    def test_live_check_does_not_print_provider_exception_text(self):
        class BrokenProvider:
            provider_id = "broken"
            model_id = "broken-model"
            def get_capabilities(self):
                return ProviderCapabilities()
            def generate(self, request):
                raise RuntimeError("secret=do-not-print")

        registry = ProviderRegistry()
        registry.register(BrokenProvider())
        stdout, stderr = StringIO(), StringIO()
        with patch("polymigrate.cli.build_provider_registry", return_value=(registry, ())), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["providers", "--check"])
        self.assertEqual(result, 1)
        self.assertIn("connectivity: FAIL (broken; RuntimeError)", stdout.getvalue())
        self.assertNotIn("do-not-print", stdout.getvalue())
        self.assertNotIn("do-not-print", stderr.getvalue())

    def test_list_models_prints_ids_without_printing_credentials(self):
        class ModelProvider:
            provider_id = "9router"
            model_id = "selected-model"
            def get_capabilities(self):
                return ProviderCapabilities()
            def list_models(self):
                return ("model-a", "model-b")

        registry = ProviderRegistry()
        registry.register(ModelProvider())
        stdout, stderr = StringIO(), StringIO()
        with patch("polymigrate.cli.build_provider_registry", return_value=(registry, ())), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["providers", "--list-models"])
        self.assertEqual(result, 0)
        self.assertIn("model-a", stdout.getvalue())
        self.assertIn("model-b", stdout.getvalue())
        self.assertNotIn("credential", stdout.getvalue().lower())
        self.assertEqual(stderr.getvalue(), "")

    def test_providers_command_is_offline_and_safe_when_unconfigured(self):
        stdout, stderr = StringIO(), StringIO()
        with patch("polymigrate.cli.build_provider_registry", return_value=(ProviderRegistry(), ())), redirect_stdout(stdout), redirect_stderr(stderr):
            result = main(["providers"])
        self.assertEqual(result, 0)
        self.assertIn("No AI providers configured", stdout.getvalue())
        self.assertNotIn("api_key", stdout.getvalue().lower())
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
