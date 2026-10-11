"""CLI tests for deterministic Python-to-Kotlin migration."""
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from polymigrate.cli import main


def fake_security_result():
    result = Mock()
    result.status = "INCOMPLETE"
    result.scanner_execution_recorded = False
    result.scanner_provenance_verified = False
    result.findings = ()
    result.warnings = ()
    result.to_dict.return_value = {"status": "INCOMPLETE"}
    return result


class DeterministicPythonKotlinCLITests(unittest.TestCase):
    def test_cli_generates_kotlin_and_reports_missing_compiler_as_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("x = 6\ny = x * 7\nprint(y)\n", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.run_local_security_scanners", return_value=fake_security_result()), \
                 patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 patch("polymigrate.cli.shutil.which", return_value=None), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "kotlin", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            generated = (output / "Main.kt").read_text(encoding="utf-8")
            self.assertIn("var x: Int = 6", generated)
            self.assertIn("var y: Int = (x * 7)", generated)
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["target_language"], "kotlin")
            self.assertEqual(report["validation_gates"]["target_build"], "BLOCKED")

    @unittest.skipUnless(shutil.which("kotlinc") and shutil.which("java"), "Kotlin compiler and Java are required")
    def test_cli_runs_kotlin_compiler_and_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text('print("kotlin runtime")\n', encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.run_local_security_scanners", return_value=fake_security_result()), \
                 patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "kotlin", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["validation_gates"]["target_build"], "PASSED", stderr.getvalue())
            self.assertIn('println(listOf<Any>("kotlin runtime")', (output / "Main.kt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
