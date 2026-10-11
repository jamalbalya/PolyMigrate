"""Target suffix mapping tests for multi-extension languages."""
import hashlib
import json
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.pipeline import SourceProject, SourceUnit


class Provider:
    provider_id = "fake"
    def get_capabilities(self):
        return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        return ModelResponse(json.dumps({"content":"// translated","assumptions":[],"unsupported_features":[]}),"fake","test")


class ExtensionMappingTests(unittest.TestCase):
    def test_preserves_suffix_when_target_language_supports_it(self):
        providers = ProviderRegistry()
        providers.register(Provider())
        source = "# header"
        project = SourceProject(Path("."), "cpp", (
            SourceUnit("include/types.h", source, hashlib.sha256(source.encode()).hexdigest()),
        ))
        adapter = LLMTargetAdapter("cpp", "cpp", ".cc", providers, "fake", allow_source_upload=True,
                                   target_extensions=(".cc", ".cpp", ".cxx", ".hpp", ".h"))
        generated = adapter.generate(project, {})
        self.assertEqual(generated[0].relative_path, "include/types.h")

    def test_rejects_invalid_target_suffix_mapping(self):
        with self.assertRaisesRegex(ValueError, "simple file suffixes"):
            LLMTargetAdapter("cpp", "cpp", ".cc", ProviderRegistry(), "fake",
                             target_extensions=("../escape",))


if __name__ == "__main__":
    unittest.main()
