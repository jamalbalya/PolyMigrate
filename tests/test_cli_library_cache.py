"""Cache integration tests prove same-project library research is reused."""
import json
import os
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
        return ModelResponse(json.dumps({"content":"package main\nfunc main() {}","assumptions":[],"unsupported_features":[]}),"fake",self.model_id)


class FakeGapPlanner:
    def plan(self, provider_id, project, target_language, graph_context=None, max_gaps=3, manifest_context=None):
        return DependencyGapPlan((DependencyGap("requests",("HTTP client",),"Need HTTP client.",("main.py",)),),(),("requests",))


class FakeResolutionWorkflow:
    def __init__(self): self.calls=0
    def resolve(self, provider_id, **kwargs):
        self.calls+=1
        decision=LibraryDecision("custom_implementation",None,"custom_implementation",
                                 "Custom implementation recommended.",(),(),provider_id)
        return LibraryResolutionResult(decision,("http client",),(),("No suitable candidate was verified",))


class CLILibraryCacheTests(unittest.TestCase):
    def test_library_cache_is_invalidated_when_source_manifest_changes(self):
        providers=ProviderRegistry()
        provider=FakeProvider()
        providers.register(provider)
        workflow=FakeResolutionWorkflow()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"source"
            source.mkdir()
            (source/"main.py").write_text("import requests\nprint('hello')\n",encoding="utf-8")
            manifest=source/"pyproject.toml"
            manifest.write_text("[project]\nname='demo'\nversion='1.0'\n",encoding="utf-8")
            db=root/"knowledge.sqlite"
            reports=[]
            for index, version in enumerate(("1.0", "2.0"), start=1):
                manifest.write_text(f"[project]\nname='demo'\nversion='{version}'\n",encoding="utf-8")
                output=root/f"out-{index}"
                stdout,stderr=StringIO(),StringIO()
                with patch.dict(os.environ,{"POLYMIGRATE_KNOWLEDGE_DB":str(db),"POLYMIGRATE_CACHE_DRAFTS":"1"}), \
                     patch("polymigrate.cli.build_provider_registry",return_value=(providers,())), \
                     patch("polymigrate.cli.DependencyGapPlanner",return_value=FakeGapPlanner()), \
                     patch("polymigrate.cli.LibraryResolutionWorkflow",return_value=workflow), \
                     redirect_stdout(stdout),redirect_stderr(stderr):
                    code=main(["migrate","--source",str(source),"--from","python","--to","go",
                               "--output",str(output),"--provider","fake","--allow-source-upload"])
                self.assertEqual(code,0,stderr.getvalue())
                reports.append(json.loads((output/"migration-review.json").read_text(encoding="utf-8")))
        self.assertEqual(workflow.calls,2)
        self.assertEqual(reports[0]["library_resolution"][0]["cache_status"],"UNVERIFIED_CACHED")
        self.assertEqual(reports[1]["library_resolution"][0]["cache_status"],"UNVERIFIED_CACHED")
        self.assertNotEqual(reports[0]["library_resolution"][0]["knowledge_record_id"],
                            reports[1]["library_resolution"][0]["knowledge_record_id"])

    def test_unverified_library_decision_is_reused_only_for_same_project(self):
        providers=ProviderRegistry()
        provider=FakeProvider()
        providers.register(provider)
        workflow=FakeResolutionWorkflow()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"source"
            source.mkdir()
            (source/"main.py").write_text("import requests\nprint('hello')\n",encoding="utf-8")
            source2=root/"source2"
            source2.mkdir()
            (source2/"main.py").write_text("import requests\nprint('hello')\n",encoding="utf-8")
            db=root/"knowledge.sqlite"
            reports=[]
            for index,source_dir in enumerate((source,source,source2),start=1):
                output=root/f"out-{index}"
                stdout,stderr=StringIO(),StringIO()
                with patch.dict(os.environ,{"POLYMIGRATE_KNOWLEDGE_DB":str(db),"POLYMIGRATE_CACHE_DRAFTS":"1"}), \
                     patch("polymigrate.cli.build_provider_registry",return_value=(providers,())), \
                     patch("polymigrate.cli.DependencyGapPlanner",return_value=FakeGapPlanner()), \
                     patch("polymigrate.cli.LibraryResolutionWorkflow",return_value=workflow), \
                     redirect_stdout(stdout),redirect_stderr(stderr):
                    code=main(["migrate","--source",str(source_dir),"--from","python","--to","go",
                               "--output",str(output),"--provider","fake","--allow-source-upload"])
                self.assertEqual(code,0,stderr.getvalue())
                reports.append(json.loads((output/"migration-review.json").read_text(encoding="utf-8")))
        self.assertEqual(workflow.calls,2)
        self.assertEqual(len(provider.requests),6)  # One translation and one manifest reconstruction request per run; research is counted by workflow.calls.
        self.assertEqual(reports[0]["library_resolution"][0]["cache_status"],"UNVERIFIED_CACHED")
        self.assertEqual(reports[1]["library_resolution"][0]["cache_status"],"UNVERIFIED_SAME_PROJECT_CACHE")
        self.assertEqual(reports[2]["library_resolution"][0]["cache_status"],"UNVERIFIED_CACHED")
        # The same library gap in a different project must not reuse or overwrite the first
        # project's draft record; record IDs are project-scoped even when problem fingerprints match.
        self.assertNotEqual(reports[0]["library_resolution"][0]["knowledge_record_id"],
                            reports[2]["library_resolution"][0]["knowledge_record_id"])
        self.assertTrue(any("package metadata may be stale" in warning for warning in reports[1]["warnings"]))


if __name__ == "__main__":
    unittest.main()
