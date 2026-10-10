"""Trusted scanner execution uses only allowlisted binaries and records provenance."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polymigrate.security.scanner_runner import run_trusted_security_scanners


class TrustedScannerRunnerTests(unittest.TestCase):
    def _fake_tools(self, root: Path, bandit_findings=None):
        semgrep = root / "semgrep"
        bandit = root / "bandit"
        semgrep.write_text("trusted semgrep test executable", encoding="utf-8")
        bandit.write_text("trusted bandit test executable", encoding="utf-8")
        bandit_findings = bandit_findings or []
        def fake_run(args, **kwargs):
            scanner = Path(args[0]).name
            if args[1] in {"--version", "-version"}:
                return subprocess.CompletedProcess(args, 0, stdout=f"{scanner} 1.2.3\n", stderr="")
            if scanner == "semgrep":
                output = {"errors": [], "results": []}
            elif scanner == "bandit":
                output = {"errors": [], "results": bandit_findings}
            else:
                raise AssertionError(f"unexpected scanner command: {args}")
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(output), stderr="")
        return { "semgrep": str(semgrep), "bandit": str(bandit) }, fake_run

    def test_missing_required_scanners_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            with patch("polymigrate.security.scanner_runner.shutil.which", return_value=None):
                result = run_trusted_security_scanners(root, "python")
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertEqual(result.missing_scanners, ("bandit", "semgrep"))
        self.assertFalse(result.scanner_provenance_verified)

    def test_clean_python_scans_verify_binary_and_report_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "output"
            root.mkdir()
            tools_root = Path(tmp) / "tools"
            tools_root.mkdir()
            paths, fake_run = self._fake_tools(tools_root)
            with patch("polymigrate.security.scanner_runner.shutil.which", side_effect=lambda name: paths.get(name)), \
                 patch("polymigrate.security.scanner_runner.subprocess.run", side_effect=fake_run):
                result = run_trusted_security_scanners(root, "python")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.accepted_scanners, ("bandit", "semgrep"))
        self.assertTrue(result.scanner_provenance_verified)

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
                result = run_trusted_security_scanners(root, "python")
        self.assertEqual(result.status, "FAILED")
        self.assertTrue(result.scanner_provenance_verified)
        self.assertEqual(result.findings[0]["rule_id"], "B307")

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
                result = run_trusted_security_scanners(root, "python")
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertFalse(result.scanner_provenance_verified)


if __name__ == "__main__":
    unittest.main()
