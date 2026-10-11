"""Local scanner execution uses allowlisted commands and records evidence, not trust."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from polymigrate.cli import _security_review_gate_status
from polymigrate.security.scanner_runner import _RULES_PATH, _parse_report, run_local_security_scanners


class LocalScannerRunnerTests(unittest.TestCase):
    def _fake_tools(self, root: Path, bandit_findings=None, gitleaks_findings=None, osv_findings=None):
        semgrep = root / "semgrep"
        bandit = root / "bandit"
        gitleaks = root / "gitleaks"
        osv = root / "osv-scanner"
        gosec = root / "gosec"
        for executable in (semgrep, bandit, gitleaks, osv, gosec):
            executable.write_text(f"local {executable.name} test executable", encoding="utf-8")
        bandit_findings = bandit_findings or []
        gitleaks_findings = gitleaks_findings or []
        osv_findings = osv_findings or []
        def fake_run(args, **kwargs):
            scanner = Path(args[0]).name
            if args[1] in {"--version", "-version"}:
                return subprocess.CompletedProcess(args, 0, stdout=f"{scanner} 1.2.3\n", stderr="")
            if scanner == "semgrep":
                output = {"errors": [], "results": []}
            elif scanner == "bandit":
                output = {"errors": [], "results": bandit_findings}
            elif scanner == "gitleaks":
                output = gitleaks_findings
            elif scanner == "osv-scanner":
                output = {"results": [{"packages": [{"vulnerabilities": osv_findings}]}]}
            elif scanner == "gosec":
                output = {"Errors": [], "GolangErrors": [], "Issues": []}
            else:
                raise AssertionError(f"unexpected scanner command: {args}")
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(output), stderr="")
        return {
            "semgrep": str(semgrep), "bandit": str(bandit),
            "gitleaks": str(gitleaks), "osv-scanner": str(osv), "gosec": str(gosec),
        }, fake_run

    def test_missing_required_scanners_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            with patch("polymigrate.security.scanner_runner.shutil.which", return_value=None):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.missing_scanners, ("bandit", "gitleaks", "osv-scanner", "semgrep"))
        self.assertFalse(result.scanner_provenance_verified)

    def test_go_profile_requires_gosec_gitleaks_osv_and_semgrep(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root)
            with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_local_security_scanners(root, "go")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.required_scanners, ("gitleaks", "gosec", "osv-scanner", "semgrep"))
        self.assertEqual(result.accepted_scanners, ("gitleaks", "gosec", "osv-scanner", "semgrep"))
        self.assertFalse(result.scanner_provenance_verified)

    def test_clean_python_scans_record_binary_and_report_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root)
            with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.accepted_scanners, ("bandit", "gitleaks", "osv-scanner", "semgrep"))
        self.assertFalse(result.scanner_provenance_verified)
        self.assertTrue(result.scanner_execution_recorded)
        self.assertEqual(_security_review_gate_status(result), "INCOMPLETE")

    def test_pinned_scanner_binary_hashes_allow_provenance_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root)
            pins = {
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_SEMGREP":
                    hashlib.sha256(Path(paths["semgrep"]).read_bytes()).hexdigest(),
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_BANDIT":
                    hashlib.sha256(Path(paths["bandit"]).read_bytes()).hexdigest(),
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_GITLEAKS":
                    hashlib.sha256(Path(paths["gitleaks"]).read_bytes()).hexdigest(),
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_OSV_SCANNER":
                    hashlib.sha256(Path(paths["osv-scanner"]).read_bytes()).hexdigest(),
                "POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256":
                    hashlib.sha256(_RULES_PATH.read_bytes()).hexdigest(),
            }
            with patch.dict("os.environ", pins), \
                 patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "PASSED")
        self.assertTrue(result.scanner_execution_recorded)
        self.assertTrue(result.scanner_provenance_verified)
        # Authenticated scanner identity is not the same as a comprehensive audit.
        self.assertEqual(_security_review_gate_status(result), "INCOMPLETE")
        self.assertTrue(result.to_dict()["scanner_provenance_verified"])
        self.assertEqual(
            _security_review_gate_status(
                result, SimpleNamespace(status="PASSED"), SimpleNamespace(status="PASSED")
            ),
            "PASSED",
        )

    def test_mismatched_scanner_pin_keeps_review_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root)
            pins = {
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_SEMGREP": "0" * 64,
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_BANDIT":
                    hashlib.sha256(Path(paths["bandit"]).read_bytes()).hexdigest(),
                "POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256":
                    hashlib.sha256(_RULES_PATH.read_bytes()).hexdigest(),
            }
            with patch.dict("os.environ", pins), \
                 patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "PASSED")
        self.assertFalse(result.scanner_provenance_verified)
        self.assertEqual(_security_review_gate_status(result), "INCOMPLETE")
        self.assertTrue(any("does not match" in warning for warning in result.provenance_warnings))

    def test_mismatched_semgrep_rules_pin_keeps_review_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root)
            pins = {
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_SEMGREP":
                    hashlib.sha256(Path(paths["semgrep"]).read_bytes()).hexdigest(),
                "POLYMIGRATE_TRUSTED_SCANNER_SHA256_BANDIT":
                    hashlib.sha256(Path(paths["bandit"]).read_bytes()).hexdigest(),
                "POLYMIGRATE_TRUSTED_SEMGREP_RULES_SHA256": "0" * 64,
            }
            with patch.dict("os.environ", pins):
                with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)):
                    with patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                        result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "PASSED")
        self.assertFalse(result.scanner_provenance_verified)
        self.assertEqual(_security_review_gate_status(result), "INCOMPLETE")
        self.assertTrue(any("rules SHA-256 does not match" in warning for warning in result.provenance_warnings))

    def test_high_bandit_finding_fails_the_security_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root, [
                {"test_id": "B307", "issue_severity": "HIGH"},
            ])
            with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "FAILED")
        self.assertFalse(result.scanner_provenance_verified)
        self.assertTrue(result.scanner_execution_recorded)
        self.assertEqual(result.findings[0]["rule_id"], "B307")


    def test_missing_report_fields_cannot_be_interpreted_as_clean_scan(self):
        self.assertEqual(_parse_report("semgrep", {"results": []}), ([], False))
        self.assertEqual(_parse_report("bandit", {"results": []}), ([], False))
        self.assertEqual(_parse_report("gosec", {"Errors": [], "GolangErrors": []}), ([], False))
        self.assertEqual(_parse_report("gosec", {
            "Errors": [], "GolangErrors": [], "Issues": []
        }), ([], True))

    def test_gitleaks_and_osv_reports_are_parsed_without_echoing_sensitive_values(self):
        self.assertEqual(
            _parse_report("gitleaks", [{"RuleID": "generic-api-key", "Secret": "must-not-escape"}]),
            ([{"severity": "HIGH", "rule_id": "GITLEAKS:generic-api-key"}], True),
        )
        self.assertEqual(
            _parse_report("osv-scanner", {"results": [{
                "packages": [{"vulnerabilities": [{"id": "GHSA-test-1234"}]}]
            }]}),
            ([{"severity": "HIGH", "rule_id": "OSV:GHSA-test-1234"}], True),
        )
        self.assertEqual(_parse_report("gitleaks", []), ([], True))
        self.assertEqual(_parse_report("osv-scanner", {"results": []}), ([], True))
        self.assertEqual(_parse_report("gitleaks", [{"Secret": "bad"}]), ([], False))
        self.assertEqual(_parse_report("osv-scanner", {"results": [{"packages": [{"vulnerabilities": [{"aliases": []}]}]}]}), ([], False))

    def test_detected_secret_blocks_security_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(
                tools_root, gitleaks_findings=[{"RuleID": "generic-api-key", "Secret": "redacted"}]
            )
            with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.findings[0]["rule_id"], "GITLEAKS:generic-api-key")
        self.assertNotIn("redacted", json.dumps(result.to_dict()))

    def test_known_dependency_vulnerability_blocks_security_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(
                tools_root, osv_findings=[{"id": "GHSA-test-1234"}]
            )
            with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.findings[0]["rule_id"], "OSV:GHSA-test-1234")

    def test_untrusted_or_malformed_scanner_output_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root)
            def malformed_run(args, **kwargs):
                if args[1] in {"--version", "-version"}:
                    return fake_run(args, **kwargs)
                return subprocess.CompletedProcess(args, 0, stdout="not-json", stderr="")
            with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=malformed_run):
                result = run_local_security_scanners(root, "python")
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertFalse(result.scanner_provenance_verified)


if __name__ == "__main__":
    unittest.main()
