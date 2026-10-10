"""Tests for safe tool registration used by migration agents."""
import tempfile
import unittest
from pathlib import Path

from polymigrate.agent.tooling import register_graphify_tool, register_library_resolution_tool, register_package_search_tool
from polymigrate.agent.tools import ToolRegistry
from polymigrate.graph.graphify import GraphResult
from polymigrate.migration.decision import LibraryDecision
from polymigrate.migration.research import LibraryResolutionResult
from polymigrate.packages.search import PackageCandidate, PackageSearchResult


class FakeSearcher:
    def search(self, language_id, query, limit=10):
        candidate=PackageCandidate("date-helper","1.0","Date helpers","npm","https://www.npmjs.com/package/date-helper")
        return PackageSearchResult(language_id,query,"available",(candidate,))


class FakeGraphify:
    def __init__(self): self.root=None; self.question=None
    def query(self, root, question):
        self.root=root; self.question=question
        return GraphResult("available",output="module A calls module B")


class FakeWorkflow:
    def resolve(self, provider_id, **kwargs):
        decision=LibraryDecision("custom_implementation",None,"custom_implementation","No equivalent found.",
                                 ("Input format must be preserved",),("differential tests",),provider_id)
        return LibraryResolutionResult(decision,("query",),(),("No package selected",))


class MigrationToolingTests(unittest.TestCase):
    def test_package_search_tool_returns_json_safe_candidate_metadata(self):
        tools=ToolRegistry()
        register_package_search_tool(tools,FakeSearcher())
        result=tools.execute("search_package_registry",{"language_id":"typescript","query":"date"})
        self.assertEqual(result["status"],"available")
        self.assertEqual(result["candidates"][0]["name"],"date-helper")
        with self.assertRaisesRegex(ValueError,"Unknown tool argument"):
            tools.execute("search_package_registry",{"language_id":"typescript","query":"date","url":"https://example.com"})

    def test_graphify_tool_uses_fixed_project_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            graph=FakeGraphify()
            tools=ToolRegistry()
            register_graphify_tool(tools,Path(tmp),graph)
            result=tools.execute("inspect_graph",{"question":"trace callers"})
            self.assertEqual(result["status"],"available")
            self.assertEqual(graph.root,Path(tmp).resolve())
            self.assertEqual(graph.question,"trace callers")

    def test_library_resolution_tool_returns_auditable_decision(self):
        tools=ToolRegistry()
        register_library_resolution_tool(tools,FakeWorkflow(),"fake")
        result=tools.execute("resolve_library_gap",{
            "source_library":"old-lib","target_language":"go","required_capabilities":["parse data"],
        })
        self.assertEqual(result["decision"]["strategy"],"custom_implementation")
        self.assertEqual(result["warnings"],["No package selected"])
        with self.assertRaisesRegex(ValueError,"required_capabilities"):
            tools.execute("resolve_library_gap",{"source_library":"old-lib","target_language":"go","required_capabilities":"parse data"})


if __name__ == "__main__":
    unittest.main()
