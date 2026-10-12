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

    def test_javascript_typescript_suffixes_follow_the_language_pair(self):
        js_extensions = (".js", ".mjs", ".cjs", ".jsx")
        ts_extensions = (".ts", ".mts", ".cts", ".tsx")
        cases = (
            ("javascript", "typescript", "src/main.js", ".ts", ts_extensions, "src/main.ts"),
            ("javascript", "typescript", "src/main.mjs", ".ts", ts_extensions, "src/main.mts"),
            ("javascript", "typescript", "src/main.cjs", ".ts", ts_extensions, "src/main.cts"),
            ("javascript", "typescript", "src/view.jsx", ".ts", ts_extensions, "src/view.tsx"),
            ("typescript", "javascript", "src/main.ts", ".js", js_extensions, "src/main.js"),
            ("typescript", "javascript", "src/main.mts", ".js", js_extensions, "src/main.mjs"),
            ("typescript", "javascript", "src/main.cts", ".js", js_extensions, "src/main.cjs"),
            ("typescript", "javascript", "src/view.tsx", ".js", js_extensions, "src/view.jsx"),
        )
        for source_language, target_language, path, target_extension, extensions, expected in cases:
            with self.subTest(path=path, target_language=target_language):
                providers = ProviderRegistry()
                providers.register(Provider())
                source = "const value = 1;"
                project = SourceProject(Path("."), source_language, (
                    SourceUnit(path, source, hashlib.sha256(source.encode()).hexdigest()),
                ))
                adapter = LLMTargetAdapter(
                    target_language, source_language, target_extension, providers, "fake",
                    allow_source_upload=True, target_extensions=extensions,
                )
                generated = adapter.generate(project, {})
                self.assertEqual(generated[0].relative_path, expected)

    def test_same_language_preserves_supported_module_suffix(self):
        providers = ProviderRegistry()
        providers.register(Provider())
        source = "export const value = 1;"
        project = SourceProject(Path("."), "typescript", (
            SourceUnit("src/main.mts", source, hashlib.sha256(source.encode()).hexdigest()),
        ))
        adapter = LLMTargetAdapter(
            "typescript", "typescript", ".ts", providers, "fake", allow_source_upload=True,
            target_extensions=(".ts", ".mts", ".cts", ".tsx"),
        )
        self.assertEqual(adapter.generate(project, {})[0].relative_path, "src/main.mts")

    def test_rejects_invalid_target_suffix_mapping(self):
        with self.assertRaisesRegex(ValueError, "simple file suffixes"):
            LLMTargetAdapter("cpp", "cpp", ".cc", ProviderRegistry(), "fake",
                             target_extensions=("../escape",))


if __name__ == "__main__":
    unittest.main()
