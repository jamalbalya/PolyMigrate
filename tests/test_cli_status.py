"""Regression tests for evidence-derived public migration statuses."""
import unittest

from polymigrate.cli import _derive_final_status


REQUIRED_GATES = {
    "target_build",
    "unit_tests",
    "integration_tests",
    "e2e_tests",
    "behavior_comparison",
}


class FinalStatusTests(unittest.TestCase):
    def passing_gates(self):
        return {name: "PASSED" for name in REQUIRED_GATES}

    def derive(self, gates, security="PASSED", dependency="PASSED"):
        return _derive_final_status(
            gates,
            security_status=security,
            dependency_status=dependency,
            required_gates=REQUIRED_GATES,
        )

    def test_success_requires_every_required_gate_and_review_to_pass(self):
        self.assertEqual(self.derive(self.passing_gates()), "SUCCESS")

    def test_unrun_required_gate_produces_partial(self):
        gates = self.passing_gates()
        gates["behavior_comparison"] = "NOT_RUN"
        self.assertEqual(self.derive(gates), "PARTIAL")

    def test_missing_required_gate_produces_partial(self):
        gates = self.passing_gates()
        del gates["e2e_tests"]
        self.assertEqual(self.derive(gates), "PARTIAL")

    def test_failed_required_gate_blocks(self):
        gates = self.passing_gates()
        gates["target_build"] = "FAILED"
        self.assertEqual(self.derive(gates), "BLOCKED")

    def test_security_review_required_blocks(self):
        self.assertEqual(
            self.derive(self.passing_gates(), security="REVIEW_REQUIRED"),
            "BLOCKED",
        )

    def test_unverified_dependency_review_blocks(self):
        self.assertEqual(
            self.derive(self.passing_gates(), dependency="UNVERIFIED"),
            "BLOCKED",
        )

    def test_unrun_security_review_produces_partial(self):
        self.assertEqual(
            self.derive(self.passing_gates(), security="NOT_RUN"),
            "PARTIAL",
        )

    def test_unverified_but_nonblocking_dependency_is_not_success(self):
        self.assertEqual(
            self.derive(self.passing_gates(), dependency="NOT_RUN"),
            "PARTIAL",
        )


if __name__ == "__main__":
    unittest.main()
