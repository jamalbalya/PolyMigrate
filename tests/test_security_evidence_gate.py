"""Tests for fail-closed aggregation of external security scanner evidence."""
import unittest

from polymigrate.security.evidence_gate import evaluate_security_evidence


HASH = "a" * 64


def evidence(scanner="bandit", **overrides):
    item = {
        "scanner_id": scanner,
        "scanner_version": "1.8.0",
        "complete": True,
        "exit_code": 0,
        "report_sha256": HASH,
        "findings": [],
    }
    item.update(overrides)
    return item


class SecurityEvidenceGateTests(unittest.TestCase):
    def test_pass_requires_every_configured_scanner_with_complete_evidence(self):
        result = evaluate_security_evidence(
            [evidence("bandit"), evidence("semgrep")],
            required_scanners={"bandit", "semgrep"},
        )
        self.assertEqual(result.status, "PASSED")
        report = result.to_dict()
        self.assertFalse(report["scanner_provenance_verified"])
        self.assertTrue(report["not_a_comprehensive_audit"])

    def test_missing_scanner_is_incomplete_not_passed(self):
        result = evaluate_security_evidence([evidence()], required_scanners={"bandit", "gosec"})
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.missing_scanners, ("gosec",))

    def test_incomplete_scan_is_not_passed(self):
        result = evaluate_security_evidence(
            [evidence(complete=False)], required_scanners={"bandit"}
        )
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.accepted_scanners, ())

    def test_nonzero_exit_is_not_passed(self):
        result = evaluate_security_evidence(
            [evidence(exit_code=2)], required_scanners={"bandit"}
        )
        self.assertEqual(result.status, "INCOMPLETE")

    def test_invalid_digest_is_not_passed(self):
        result = evaluate_security_evidence(
            [evidence(report_sha256="not-a-digest")], required_scanners={"bandit"}
        )
        self.assertEqual(result.status, "INCOMPLETE")

    def test_high_finding_fails_gate_without_echoing_finding_message(self):
        result = evaluate_security_evidence(
            [evidence(findings=[{"severity": "HIGH", "rule_id": "RULE-1", "message": "secret-value"}])],
            required_scanners={"bandit"},
        )
        self.assertEqual(result.status, "FAILED")
        self.assertNotIn("secret-value", str(result.to_dict()))

    def test_medium_finding_requires_review(self):
        result = evaluate_security_evidence(
            [evidence(findings=[{"severity": "MEDIUM", "rule_id": "RULE-2"}])],
            required_scanners={"bandit"},
        )
        self.assertEqual(result.status, "REVIEW_REQUIRED")

    def test_malformed_finding_blocks_pass(self):
        result = evaluate_security_evidence(
            [evidence(findings=[{"severity": "mystery", "rule_id": "RULE-3"}])],
            required_scanners={"bandit"},
        )
        self.assertEqual(result.status, "INCOMPLETE")

    def test_duplicate_and_unconfigured_scanners_are_reported(self):
        result = evaluate_security_evidence(
            [evidence(), evidence(), evidence("trivy")],
            required_scanners={"bandit"},
        )
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertTrue(any("Duplicate" in error for error in result.errors))
        self.assertTrue(any("unconfigured" in error for error in result.errors))

    def test_empty_required_scanner_set_is_incomplete(self):
        result = evaluate_security_evidence([], required_scanners=set())
        self.assertEqual(result.status, "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
