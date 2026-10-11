"""CLI tests for deterministic Python-to-Java migration."""
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
class DeterministicPythonJavaCLITests(unittest.TestCase):
    def test_migration_generates_and_runs_java_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("x = 6\ny = x * 7\nprint(y)\n", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "java", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            self.assertTrue((output / "Main.java").is_file())
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["target_language"], "java")
            self.assertEqual(report["validation_gates"]["target_build"], "PASSED")
            self.assertTrue(any(item["command_id"] == "target_runtime_smoke" and item["status"] == "PASSED"
                                for item in report["validation_results"]["executions"]))

    def test_print_supports_multiple_values_and_empty_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text(
                'name = "Jamal"\\ncount = 3\\nprint(name, count, True)\\nprint()\\n',
                encoding="utf-8",
            )
            output = root / "out"
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \\
                 redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "java", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3)
            classes = output / "classes"
            classes.mkdir()
            compile_result = subprocess.run(
                ["javac", "-d", str(classes), str(output / "Main.java")],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(
                ["java", "-cp", str(classes), "Main"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stderr)
            self.assertEqual(run_result.stdout, "Jamal 3 True\\n\\n")


if __name__ == "__main__":
    unittest.main()
