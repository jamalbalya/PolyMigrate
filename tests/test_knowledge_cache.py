"""Knowledge cache tests prove identical work is reused only within the configured scope."""
import json
import tempfile
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.knowledge import MigrationKnowledgeStore
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class CountingProvider:
    provider_id = "fake"
    model_id = "test-model"
    def __init__(self):
        self.requests = []
    def get_capabilities(self):
        return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        self.requests.append(request)
        return ModelResponse(json.dumps({
            "content": "package main", "assumptions": [], "unsupported_features": [],
        }), "fake", self.model_id)


class KnowledgeCacheTests(unittest.TestCase):
    def _engine(self, source, provider, store, scope):
        providers = ProviderRegistry()
        providers.register(provider)
        registry = AdapterRegistry()
        registry.register_source(InventorySourceAdapter("python", (".py",)))
        registry.register_target(LLMTargetAdapter(
            "go", "python", ".go", providers, "fake", allow_source_upload=True,
            knowledge_store=store, project_scope=scope, cache_drafts=True,
        ))
        return MigrationEngine(registry)

    def test_identical_translation_reuses_same_project_draft_without_model_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text("print('hello')", encoding="utf-8")
            store = MigrationKnowledgeStore(Path(tmp) / "knowledge.sqlite")
            provider = CountingProvider()
            engine = self._engine(root, provider, store, "project-scope-hash")
            first = engine.execute(root, "python", "go", Path(tmp) / "out-1", {"graphify_context": "calls A -> B"})
            second = engine.execute(root, "python", "go", Path(tmp) / "out-2", {"graphify_context": "calls A -> B"})
            self.assertEqual(len(provider.requests), 1)
            self.assertEqual(first.status, "GENERATED_UNVERIFIED")
            self.assertTrue(any("same-project unverified draft" in w for w in second.warnings))
            self.assertTrue((Path(tmp) / "out-2" / "main.go").is_file())

    def test_changed_graph_context_invalidates_draft_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text("print('hello')", encoding="utf-8")
            store = MigrationKnowledgeStore(Path(tmp) / "knowledge.sqlite")
            provider = CountingProvider()
            engine = self._engine(root, provider, store, "project-scope-hash")
            engine.execute(root, "python", "go", Path(tmp) / "out-1", {"graphify_context": "old graph"})
            engine.execute(root, "python", "go", Path(tmp) / "out-2", {"graphify_context": "updated graph"})
            self.assertEqual(len(provider.requests), 2)


if __name__ == "__main__":
    unittest.main()
