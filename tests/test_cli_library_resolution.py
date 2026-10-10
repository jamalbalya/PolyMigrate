"""CLI integration test for autonomous library-gap resolution before file translation."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.cli import main
from polymigrate.migration.decision import LibraryDecision
from polymigrate.migration.dependencies import DependencyGap, DependencyGapPlan
from polymigrate.migration.research import LibraryResolutionResult


class FakeProvider:
    provider_id="fake"
    model_id="test-model"
    def __init__(self): self.requests=[]
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self,request:ModelRequest):
        self.requests.append(request)
        return ModelResponse(json.dumps({"content":"package main","assumptions":[],"unsupported_features":[]}),"fake",self.model_id)


class FakeGapPlanner:
    def plan(self, provider_id, project, target_language, graph_context=None, max_gaps=3, manifest_context=None):
        return DependencyGapPlan((DependencyGap("requests",("HTTP client","retry behavior"),
                                               "Source imports requests.",("main.py",)),),(),("requests",))


class FakeResolutionWorkflow:
    def resolve(self, provider_id, **kwargs):
        decision=LibraryDecision("custom_implementation",None,"custom_implementation",
                                 "No verified target package was selected.",
                                 ("Preserve timeout behavior",),("Differential HTTP tests",),provider_id)
        return LibraryResolutionResult(decision,("http client retry",),(),("No suitable candidate was verified",))


class CLILibraryResolutionTests(unittest.TestCase):
    def test_library_gap_plan_is_reported_and_passed_to_translation(self):
        providers=ProviderRegistry()
        provider=FakeProvider()
        providers.register(provider)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source"
            source.mkdir()
            (source/"main.py").write_text("import requests\nprint(requests.get('https://example.invalid'))\n",encoding="utf-8")
            output=Path(tmp)/"out"
            stdout,stderr=StringIO(),StringIO()
            with patch("polymigrate.cli.build_provider_registry",return_value=(providers,())), \
                 patch("polymigrate.cli.DependencyGapPlanner",return_value=FakeGapPlanner()), \
                 patch("polymigrate.cli.LibraryResolutionWorkflow",return_value=FakeResolutionWorkflow()), \
                 redirect_stdout(stdout),redirect_stderr(stderr):
                code=main(["migrate","--source",str(source),"--from","python","--to","go",
                           "--output",str(output),"--provider","fake","--allow-source-upload"])
            report=json.loads((output/"migration-review.json").read_text(encoding="utf-8"))
        self.assertEqual(code,0,stderr.getvalue())
        self.assertEqual(report["dependency_inventory"],["requests"])
        self.assertEqual(report["library_resolution"][0]["strategy"],"custom_implementation")
        self.assertEqual(report["library_resolution"][0]["implementation_status"],"CUSTOM_IMPLEMENTATION_RECOMMENDED")
        self.assertIn("library_resolution",provider.requests[0].prompt)
        self.assertIn("custom_implementation",provider.requests[0].prompt)
        self.assertIn("migration_skills",provider.requests[0].prompt)
        self.assertIn("library-replacement",provider.requests[0].prompt)


if __name__ == "__main__":
    unittest.main()
