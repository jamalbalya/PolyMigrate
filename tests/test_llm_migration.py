"""Tests for the experimental provider-backed translation path."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class TranslationProvider:
    provider_id = "fake"
    def __init__(self, response):
        self.response = response
        self.requests = []
    def get_capabilities(self):
        return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        self.requests.append(request)
        return ModelResponse(self.response, "fake", "test-model")


def registry_for(provider, *, allow_upload=True, max_source_chars=100_000):
    providers = ProviderRegistry()
    providers.register(provider)
    adapters = AdapterRegistry()
    adapters.register_source(InventorySourceAdapter("python", (".py",)))
    adapters.register_target(LLMTargetAdapter(
        "go", "python", ".go", providers, "fake",
        allow_source_upload=allow_upload, max_source_chars=max_source_chars,
    ))
    return MigrationEngine(adapters)


class LLMTranslationTests(unittest.TestCase):
    def test_translates_file_and_reports_unverified_status(self):
        provider = TranslationProvider(json.dumps({
            "content": "package main\nfunc main() {}\n",
            "assumptions": [], "unsupported_features": [],
        }))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            source_file = source / "main.py"
            source_file.write_text("print('hello')", encoding="utf-8")
            output = Path(tmp) / "out"
            result = registry_for(provider).execute(source, "python", "go", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertEqual(result.generated_files, ("main.go",))
            self.assertTrue((output / "main.go").is_file())
            self.assertEqual(source_file.read_text(encoding="utf-8"), "print('hello')")
            self.assertTrue(any("not yet passed build" in warning for warning in result.warnings))

    def test_source_upload_requires_explicit_opt_in(self):
        provider = TranslationProvider(json.dumps({"content":"package main","assumptions":[],"unsupported_features":[]}))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print('hello')", encoding="utf-8")
            output = Path(tmp) / "out"
            with self.assertRaisesRegex(PermissionError, "Source upload is disabled"):
                registry_for(provider, allow_upload=False).execute(source, "python", "go", output)
            self.assertEqual(provider.requests, [])
            self.assertFalse(output.exists())

    def test_invalid_model_response_does_not_create_output(self):
        provider = TranslationProvider("not valid json")
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print('hello')", encoding="utf-8")
            output = Path(tmp) / "out"
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                registry_for(provider).execute(source, "python", "go", output)
            self.assertFalse(output.exists())

    def test_recognizable_secret_is_redacted_before_provider_call(self):
        provider = TranslationProvider(json.dumps({
            "content": "package main", "assumptions": [], "unsupported_features": [],
        }))
        secret_source = 'API_KEY = "sk-12345678901234567890"'
        source_project = SourceProject(Path("."), "python", (
            SourceUnit("settings.py", secret_source, hashlib.sha256(secret_source.encode()).hexdigest()),
        ))
        target = LLMTargetAdapter("go", "python", ".go", ProviderRegistry(), "fake", allow_source_upload=True)
        providers = ProviderRegistry()
        providers.register(provider)
        target.providers = providers
        target.generate(source_project, {})
        self.assertNotIn("sk-12345678901234567890", provider.requests[0].prompt)
        self.assertTrue(any("redacted" in warning for warning in target.warnings))

    def test_manifest_context_is_redacted_before_provider_prompt(self):
        provider = TranslationProvider(json.dumps({
            "content": "package main", "assumptions": [], "unsupported_features": [],
        }))
        providers = ProviderRegistry()
        providers.register(provider)
        target = LLMTargetAdapter("go", "python", ".go", providers, "fake", allow_source_upload=True)
        source_text = "print('hello')"
        project = SourceProject(Path("."), "python", (
            SourceUnit("main.py", source_text, hashlib.sha256(source_text.encode()).hexdigest()),
        ))
        target.generate(project, {
            "source_manifests": [{
                "path": "package.json",
                "content": '{"name":"demo","api_key":"sk-12345678901234567890"}',
            }],
        })
        prompt = provider.requests[0].prompt
        self.assertIn("package.json", prompt)
        self.assertNotIn("sk-12345678901234567890", prompt)
        self.assertIn("[REDACTED]", prompt)

    def test_inventory_skips_ignored_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("print(1)", encoding="utf-8")
            ignored = root / "node_modules"
            ignored.mkdir()
            (ignored / "vendor.py").write_text("print(2)", encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            self.assertEqual([unit.relative_path for unit in project.units], ["main.py"])


if __name__ == "__main__":
    unittest.main()
