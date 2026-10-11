"""Resource budget tests for provider-backed translation."""
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


class CountingProvider:
    provider_id = "fake"
    def __init__(self, output):
        self.output = output
        self.calls = 0
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        self.calls += 1
        return ModelResponse(json.dumps({"content":self.output,"assumptions":[],"unsupported_features":[]}),"fake","test")


def make_unit(path, text):
    return SourceUnit(path, text, hashlib.sha256(text.encode()).hexdigest())


class TranslationBudgetTests(unittest.TestCase):
    def test_file_count_limit_fails_before_provider_calls(self):
        provider=CountingProvider("package main")
        providers=ProviderRegistry()
        providers.register(provider)
        adapter=LLMTargetAdapter("go","python",".go",providers,"fake",allow_source_upload=True,max_files_per_run=1)
        project=SourceProject(Path("."),"python",(make_unit("a.py","a"),make_unit("b.py","b")))
        with self.assertRaisesRegex(ValueError,"file limit"):
            adapter.generate(project,{})
        self.assertEqual(provider.calls,0)

    def test_total_source_context_limit_fails_before_provider_calls(self):
        provider=CountingProvider("package main")
        providers=ProviderRegistry()
        providers.register(provider)
        adapter=LLMTargetAdapter("go","python",".go",providers,"fake",allow_source_upload=True,
                                 max_source_chars=100,max_total_source_chars=5)
        project=SourceProject(Path("."),"python",(make_unit("a.py","123456"),))
        with self.assertRaisesRegex(ValueError,"total translation context limit"):
            adapter.generate(project,{})
        self.assertEqual(provider.calls,0)

    def test_total_output_limit_fails_without_writing_project(self):
        provider=CountingProvider("x" * 20)
        providers=ProviderRegistry()
        providers.register(provider)
        adapter=LLMTargetAdapter("go","python",".go",providers,"fake",allow_source_upload=True,
                                 max_total_output_chars=10)
        adapters=AdapterRegistry()
        adapters.register_source(InventorySourceAdapter("python",(".py",)))
        adapters.register_target(adapter)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source"
            source.mkdir()
            (source/"main.py").write_text("print(1)",encoding="utf-8")
            output=Path(tmp)/"out"
            with self.assertRaisesRegex(ValueError,"total output limit"):
                MigrationEngine(adapters).execute(source,"python","go",output)
            self.assertFalse(output.exists())
        self.assertEqual(provider.calls,1)


if __name__ == "__main__":
    unittest.main()
