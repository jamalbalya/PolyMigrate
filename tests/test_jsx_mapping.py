"""Regression coverage for JSX to TSX output mapping."""
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
        return ModelResponse(json.dumps({"content":"export default function App(){ return null }","assumptions":[],"unsupported_features":[]}),"fake","test")


class JSXMappingTests(unittest.TestCase):
    def test_jsx_maps_to_tsx_for_typescript_target(self):
        providers=ProviderRegistry()
        providers.register(Provider())
        text="export default () => <div />"
        project=SourceProject(Path("."),"javascript",(
            SourceUnit("src/App.jsx",text,hashlib.sha256(text.encode()).hexdigest()),
        ))
        adapter=LLMTargetAdapter("typescript","javascript",".ts",providers,"fake",allow_source_upload=True,
                                 target_extensions=(".ts",".mts",".cts",".tsx"))
        self.assertEqual(adapter.generate(project,{})[0].relative_path,"src/App.tsx")


if __name__ == "__main__":
    unittest.main()
