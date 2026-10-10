"""CLI integration tests for external security evidence reporting."""
import json
import tempfile
import unittest
from pathlib import Path

from polymigrate.cli import _load_security_evidence, build_parser


class SecurityEvidenceCLITests(unittest.TestCase):
    def test_security_evidence_is_optional_but_missing_evidence_is_incomplete(self):
        result = _load_security_evidence(None)
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertTrue(result.to_dict()["not_a_comprehensive_audit"])
        self.assertFalse(result.to_dict()["scanner_provenance_verified"])

    def test_external_evidence_file_is_validated_and_summarized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "security-evidence.json"
            path.write_text(json.dumps({
                "required_scanners": ["scanner-a"],
                "evidence": [{
                    "scanner_id": "scanner-a",
                    "scanner_version": "1.2.3",
                    "complete": True,
                    "exit_code": 0,
                    "report_sha256": "a" * 64,
                    "findings": [],
                }],
            }), encoding="utf-8")
            result = _load_security_evidence(path)
        self.assertEqual(result.status, "PASSED")
        report = result.to_dict()
        self.assertEqual(report["accepted_scanners"], ["scanner-a"])
        self.assertFalse(report["scanner_provenance_verified"])
        self.assertTrue(report["not_a_comprehensive_audit"])

    def test_malformed_evidence_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "security-evidence.json"
            path.write_text('{"required_scanners": "scanner-a", "evidence": []}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "required_scanners must be a list"):
                _load_security_evidence(path)

    def test_migrate_parser_exposes_external_evidence_option(self):
        args = build_parser().parse_args([
            "migrate", "--source", ".", "--from", "python", "--to", "go",
            "--output", "./out", "--security-evidence", "./evidence.json",
        ])
        self.assertEqual(args.security_evidence, Path("./evidence.json"))


if __name__ == "__main__":
    unittest.main()
