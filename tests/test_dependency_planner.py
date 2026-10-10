"""Dependency extraction and AI gap planning tests."""
import json
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.dependencies import DependencyExtractor, DependencyGapPlanner
from polymigrate.migration.pipeline import SourceProject, SourceUnit


class FakeProvider:
    provider_id = "fake"
    def __init__(self, payload): self.payload=payload; self.requests=[]
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        self.requests.append(request)
        return ModelResponse(json.dumps(self.payload),"fake","test-model")


class DependencyPlannerTests(unittest.TestCase):
    def test_python_import_extractor_filters_standard_and_local_modules(self):
        project=SourceProject(Path("."),"python",(
            SourceUnit("main.py",'import requests\nfrom pandas import DataFrame\nimport json\nimport helper\n',""),
            SourceUnit("helper.py","value = 1",""),
        ))
        evidence,warnings=DependencyExtractor().extract(project)
        self.assertEqual({item.package_name for item in evidence},{"requests","pandas"})

    def test_go_group_import_extractor_filters_standard_library(self):
        source='''package main
import (
 "fmt"
 "github.com/acme/codec"
)
'''
        project=SourceProject(Path("."),"go",(SourceUnit("main.go",source,""),))
        evidence,_=DependencyExtractor().extract(project)
        self.assertEqual([item.package_name for item in evidence],["github.com/acme/codec"])

    def test_planner_accepts_only_observed_dependency_names(self):
        project=SourceProject(Path("."),"python",(
            SourceUnit("main.py","import requests\n",""),
        ))
        provider=FakeProvider({"gaps":[{"source_library":"requests","required_capabilities":["HTTP client","retry"],
                                       "reason":"Target semantics may differ.","evidence_files":["main.py"]}]})
        registry=ProviderRegistry()
        registry.register(provider)
        plan=DependencyGapPlanner(registry).plan("fake",project,"go")
        self.assertEqual(plan.gaps[0].source_library,"requests")
        self.assertEqual(plan.gaps[0].evidence_files,("main.py",))

    def test_planner_rejects_hallucinated_dependency(self):
        project=SourceProject(Path("."),"python",(SourceUnit("main.py","import requests\n",""),))
        provider=FakeProvider({"gaps":[{"source_library":"imaginary-package","required_capabilities":["do things"],
                                       "reason":"Looks useful.","evidence_files":["main.py"]}]})
        registry=ProviderRegistry()
        registry.register(provider)
        plan=DependencyGapPlanner(registry).plan("fake",project,"go")
        self.assertEqual(plan.gaps,())
        self.assertTrue(any("not present in observed imports" in warning for warning in plan.warnings))

    def test_planner_does_not_call_model_when_no_imports_are_detected(self):
        project=SourceProject(Path("."),"python",(SourceUnit("main.py","print('hello')",""),))
        provider=FakeProvider({})
        registry=ProviderRegistry()
        registry.register(provider)
        plan=DependencyGapPlanner(registry).plan("fake",project,"go")
        self.assertEqual(plan.gaps,())
        self.assertEqual(provider.requests,[])


if __name__ == "__main__":
    unittest.main()
