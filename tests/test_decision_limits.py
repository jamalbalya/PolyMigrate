"""Tests for bounded decision payloads and output."""
import json
import unittest
from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.decision import LibraryDecisionEngine, LibraryDecisionError
from polymigrate.models import LibraryCandidate


class Provider:
    provider_id="fake"
    def __init__(self,payload): self.payload=payload
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self,request:ModelRequest): return ModelResponse(json.dumps(self.payload),"fake","test")


class DecisionLimitTests(unittest.TestCase):
    def test_rejects_oversized_candidate_set_before_model_call(self):
        registry=ProviderRegistry()
        registry.register(Provider({}))
        engine=LibraryDecisionEngine(registry)
        candidates=[LibraryCandidate(f"lib-{i}","direct_replacement",0.5,0.5) for i in range(31)]
        with self.assertRaisesRegex(ValueError,"30-candidate"):
            engine.decide("fake",source_library="lib",target_language="go",required_capabilities=[],candidates=candidates)

    def test_rejects_oversized_assumption_output(self):
        registry=ProviderRegistry()
        registry.register(Provider({"decision_type":"custom_implementation","candidate_name":None,
                                    "rationale":"No package fits.","assumptions":["a"]*21,
                                    "validation_tests":["run tests"]}))
        with self.assertRaisesRegex(LibraryDecisionError,"assumptions"):
            LibraryDecisionEngine(registry).decide("fake",source_library="lib",target_language="go",
                                                   required_capabilities=[],candidates=[])


if __name__ == "__main__":
    unittest.main()
