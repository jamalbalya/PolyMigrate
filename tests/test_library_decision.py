"""Tests for AI-assisted library decisions."""
import json
import unittest
from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.decision import LibraryDecisionEngine, LibraryDecisionError
from polymigrate.models import LibraryCandidate


class DecisionProvider:
    provider_id = "fake"
    def __init__(self, content):
        self.content = content
        self.last_request = None
    def get_capabilities(self):
        return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        self.last_request = request
        return ModelResponse(self.content, "fake", "decision-test")


class LibraryDecisionTests(unittest.TestCase):
    def setUp(self):
        self.candidates = [LibraryCandidate("csvkit-go", "direct_replacement", .9, .85, .7, .9, .2)]
    def _engine(self, payload):
        provider = DecisionProvider(json.dumps(payload))
        registry = ProviderRegistry()
        registry.register(provider)
        return LibraryDecisionEngine(registry), provider
    def test_selects_only_a_supplied_candidate(self):
        engine, _ = self._engine({"decision_type":"candidate","candidate_name":"csvkit-go",
                                  "rationale":"Coverage is adequate.","assumptions":[],
                                  "validation_tests":["compare output against source"]})
        result = engine.decide("fake", source_library="pandas", target_language="go",
                               required_capabilities=["csv"], candidates=self.candidates)
        self.assertEqual(result.candidate_name, "csvkit-go")
        self.assertEqual(result.strategy, "direct_replacement")
    def test_rejects_hallucinated_candidate_name(self):
        engine, _ = self._engine({"decision_type":"candidate","candidate_name":"imaginary-lib",
                                  "rationale":"It is best.","assumptions":[],
                                  "validation_tests":["run tests"]})
        with self.assertRaisesRegex(LibraryDecisionError, "not present"):
            engine.decide("fake", source_library="pandas", target_language="go",
                          required_capabilities=["csv"], candidates=self.candidates)
    def test_can_choose_custom_implementation_when_no_library_fits(self):
        engine, _ = self._engine({"decision_type":"custom_implementation","candidate_name":None,
                                  "rationale":"No verified equivalent covers the required semantics.",
                                  "assumptions":["CSV dialect is limited to documented features"],
                                  "validation_tests":["differential CSV fixtures","malformed input cases"]})
        result = engine.decide("fake", source_library="special-parser", target_language="rust",
                               required_capabilities=["streaming"], candidates=[])
        self.assertEqual(result.strategy, "custom_implementation")
    def test_requires_validation_tests(self):
        engine, _ = self._engine({"decision_type":"custom_implementation","candidate_name":None,
                                  "rationale":"Implement the required behavior.","assumptions":[],"validation_tests":[]})
        with self.assertRaisesRegex(LibraryDecisionError, "validation_tests"):
            engine.decide("fake", source_library="lib", target_language="go",
                          required_capabilities=["feature"], candidates=[])
    def test_duplicate_candidate_names_are_rejected(self):
        engine, _ = self._engine({})
        with self.assertRaisesRegex(ValueError, "unique"):
            engine.decide("fake", source_library="lib", target_language="go", required_capabilities=[],
                          candidates=self.candidates * 2)


if __name__ == "__main__":
    unittest.main()
