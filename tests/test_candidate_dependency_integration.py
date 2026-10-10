"""Candidate-specific dependency proof requires declaration, import, and executed gates."""
import unittest
from types import SimpleNamespace

from polymigrate.cli import _candidate_dependency_integration_status


class CandidateDependencyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.review = SimpleNamespace(
            status="PASSED",
            declared_dependencies=("github.com/acme/dep",),
            observed_imports=("github.com/acme/dep",),
        )
        self.gates = {
            "target_build": "PASSED",
            "integration_tests": "PASSED",
            "behavior_comparison": "PASSED",
        }
        self.candidate = {
            "decision_type": "candidate",
            "selected_package": {"name": "github.com/acme/dep", "registry": "go-modules"},
        }

    def test_no_candidate_dependency_makes_gate_not_applicable(self):
        status, warnings = _candidate_dependency_integration_status([], self.review, self.gates, "python")
        self.assertEqual(status, "PASSED")
        self.assertIn("not applicable", warnings[0])

    def test_candidate_passes_only_when_declared_imported_and_all_required_gates_pass(self):
        status, warnings = _candidate_dependency_integration_status(
            [self.candidate], self.review, self.gates, "go"
        )
        self.assertEqual(status, "PASSED")
        self.assertIn("Each candidate package is declared and imported", warnings[0])

    def test_missing_import_does_not_pass_candidate_proof(self):
        review = SimpleNamespace(
            status="PASSED",
            declared_dependencies=("github.com/acme/dep",),
            observed_imports=("encoding/json",),
        )
        status, warnings = _candidate_dependency_integration_status(
            [self.candidate], review, self.gates, "go"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("not observed", warnings[0])

    def test_integration_gate_must_have_passed(self):
        gates = {**self.gates, "integration_tests": "NOT_RUN"}
        status, warnings = _candidate_dependency_integration_status(
            [self.candidate], self.review, gates, "go"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("integration_tests=PASSED", warnings[0])


    def test_python_candidate_stays_unverified_without_dependency_install_build(self):
        status, warnings = _candidate_dependency_integration_status(
            [self.candidate], self.review, self.gates, "python"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("not implemented for target language python", warnings[0])

    def test_repository_reference_is_not_a_package_integration_proof(self):
        candidate = {
            "decision_type": "candidate",
            "selected_package": {"name": "owner/repository", "registry": "github-repositories"},
        }
        status, warnings = _candidate_dependency_integration_status(
            [candidate], self.review, self.gates, "go"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("without a package identity", warnings[0])


if __name__ == "__main__":
    unittest.main()
