"""Library research workflow tests with deterministic provider and registry fakes."""
import json
import unittest

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.research import LibraryResolutionWorkflow
from polymigrate.packages.search import PackageCandidate, PackageSearchResult


class FakeProvider:
    provider_id = "fake"
    model_id = "test-model"
    def __init__(self, responses): self.responses=iter(responses)
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self, request: ModelRequest): return ModelResponse(next(self.responses),"fake","test-model")


class FakeSearcher:
    def __init__(self, results): self.results=iter(results); self.queries=[]
    def search(self, language_id, query, limit=10):
        self.queries.append((language_id,query,limit))
        return next(self.results)


class LibraryResearchTests(unittest.TestCase):
    def _workflow(self, responses, search_results):
        provider=FakeProvider([json.dumps(item) for item in responses])
        providers=ProviderRegistry()
        providers.register(provider)
        searcher=FakeSearcher(search_results)
        return LibraryResolutionWorkflow(providers,searcher),searcher

    def test_searches_registry_then_selects_only_discovered_candidate(self):
        package=PackageCandidate("date-helper","1.2.3","Date utilities","npm","https://www.npmjs.com/package/date-helper","MIT")
        workflow,searcher=self._workflow([
            {"queries":["date parsing"]},
            {"decision_type":"candidate","candidate_name":"npm:date-helper","rationale":"Metadata suggests relevant date helpers.",
             "assumptions":["Timezone semantics must be tested"],"validation_tests":["compare timezone edge cases"]},
        ],[PackageSearchResult("typescript","date parsing","available",(package,))])
        result=workflow.resolve("fake",source_library="moment",target_language="typescript",
                                required_capabilities=["date parsing","timezone"])
        self.assertEqual(result.decision.candidate_name,"npm:date-helper")
        self.assertEqual(searcher.queries,[("typescript","date parsing",5)])
        self.assertTrue(any("not a verified replacement" in warning for warning in result.warnings))

    def test_no_candidates_leads_to_custom_implementation_option(self):
        workflow,searcher=self._workflow([
            {"queries":["special binary format"]},
            {"decision_type":"custom_implementation","candidate_name":None,
             "rationale":"No candidate was found with sufficient evidence.",
             "assumptions":["The format specification is available"],
             "validation_tests":["golden file comparisons","malformed input tests"]},
        ],[PackageSearchResult("go","special binary format","empty",(), "No candidates")])
        result=workflow.resolve("fake",source_library="binary-lib",target_language="go",
                                required_capabilities=["decode custom format"])
        self.assertEqual(result.decision.strategy,"custom_implementation")
        self.assertTrue(any("must create a replacement" in warning for warning in result.warnings))

    def test_query_budget_is_enforced(self):
        workflow,_=self._workflow([{"queries":["a","b","c","d"]},{"decision_type":"custom_implementation",
                                   "candidate_name":None,"rationale":"No package candidate is suitable.",
                                   "assumptions":[],"validation_tests":["differential tests"]}],
                                  [PackageSearchResult("rust","a","empty",()),PackageSearchResult("rust","b","empty",()),PackageSearchResult("rust","c","empty",())])
        result=workflow.resolve("fake",source_library="source-lib",target_language="rust",
                                required_capabilities=["feature"],max_queries=3)
        self.assertEqual(len(result.searched_queries),3)
        self.assertEqual(len(result.candidates),0)

    def test_github_repository_is_reference_only_not_installable_package(self):
        repository=PackageCandidate("org/codec",None,"Reference implementation","github-repositories","https://github.com/org/codec")
        workflow,_=self._workflow([
            {"queries":["codec implementation"]},
            {"decision_type":"candidate","candidate_name":"github-repositories:org/codec",
             "rationale":"Repository contains a potentially useful reference.",
             "assumptions":["API compatibility must be assessed"],"validation_tests":["port behavior tests"]},
        ],[PackageSearchResult("go","codec implementation","available",(repository,))])
        result=workflow.resolve("fake",source_library="source-codec",target_language="go",
                                required_capabilities=["decode codec"])
        self.assertEqual(result.decision.strategy,"reference_repository")
        self.assertTrue(any("reference material only" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
