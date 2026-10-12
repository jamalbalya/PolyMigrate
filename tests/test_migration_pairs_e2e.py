"""Multi-pair migration contract fixtures using a deterministic provider (no live API claims)."""
import json
import tempfile
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.languages import LanguageRegistry
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class PairFixtureProvider:
    provider_id = "fixture"
    model_id = "fixture-model"

    def __init__(self):
        self.requests = []

    def get_capabilities(self):
        return ProviderCapabilities()

    def generate(self, request: ModelRequest):
        self.requests.append(request)
        target = request.context["target_language"]
        payload = {
            "content": f"fixture output for {target}\n",
            "assumptions": ["Deterministic contract fixture; not a semantic-equivalence claim."],
            "unsupported_features": [],
        }
        return ModelResponse(json.dumps(payload), self.provider_id, self.model_id)


_REGISTERED_LANGUAGES = LanguageRegistry().all()


class MultiPairMigrationE2ETests(unittest.TestCase):
    # Exercise every directed, non-identity pair in the language registry. The fake
    # provider validates orchestration, source isolation, and target path mapping only;
    # it does not prove semantic equivalence or real-provider quality.
    PAIRS = tuple(
        (source.id, target.id)
        for source in _REGISTERED_LANGUAGES
        for target in _REGISTERED_LANGUAGES
        if source.id != target.id
    )

    def test_matrix_covers_every_directed_non_identity_pair(self):
        language_ids = {language.id for language in _REGISTERED_LANGUAGES}
        self.assertEqual(len(language_ids), len(_REGISTERED_LANGUAGES))
        self.assertEqual(len(self.PAIRS), len(language_ids) * (len(language_ids) - 1))
        self.assertEqual(len(set(self.PAIRS)), len(self.PAIRS))
        for source_id in language_ids:
            for target_id in language_ids:
                if source_id != target_id:
                    self.assertIn((source_id, target_id), self.PAIRS)

    def test_all_registered_language_pairs_write_isolated_unverified_artifacts(self):
        languages = LanguageRegistry()
        for source_id, target_id in self.PAIRS:
            with self.subTest(source=source_id, target=target_id), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / "source"
                source.mkdir()
                source_path = source / ("main" + languages.get(source_id).extensions[0])
                original = "fixture source; preserve it"
                source_path.write_text(original, encoding="utf-8")
                output = root / "generated"
                provider = PairFixtureProvider()
                providers = ProviderRegistry()
                providers.register(provider)
                adapters = AdapterRegistry()
                adapters.register_source(InventorySourceAdapter(source_id, languages.get(source_id).extensions))
                adapters.register_target(LLMTargetAdapter(
                    target_id, source_id, languages.get(target_id).extensions[0],
                    providers, "fixture", allow_source_upload=True,
                    target_extensions=languages.get(target_id).extensions,
                ))
                result = MigrationEngine(adapters).execute(source, source_id, target_id, output)
                expected = output / ("main" + languages.get(target_id).extensions[0])
                self.assertEqual(result.status, "GENERATED_UNVERIFIED")
                self.assertTrue(expected.is_file())
                self.assertIn(f"fixture output for {target_id}", expected.read_text(encoding="utf-8"))
                self.assertEqual(source_path.read_text(encoding="utf-8"), original)
                self.assertEqual(len(provider.requests), 1)
                self.assertEqual(provider.requests[0].context["source_language"], source_id)
                self.assertEqual(provider.requests[0].context["target_language"], target_id)


if __name__ == "__main__":
    unittest.main()
