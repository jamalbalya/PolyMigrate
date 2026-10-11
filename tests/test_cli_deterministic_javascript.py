"""CLI tests for deterministic Python-to-JavaScript migration."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main
from polymigrate.security.scanner_runner import run_local_security_scanners
from polymigrate.validation.dependency_wiring import review_dependency_wiring


class DeterministicPythonJavaScriptCLITests(unittest.TestCase):
    def test_migration_generates_javascript_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("x = 6\ny = x * 7\nprint(y)\n", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.run_local_security_scanners", wraps=run_local_security_scanners) as security_runner, \
                 patch("polymigrate.cli.review_dependency_wiring", wraps=review_dependency_wiring) as dependency_review, \
                 patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 patch("polymigrate.cli.shutil.which", return_value=None), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "javascript", "--output", str(output),
                    "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            security_runner.assert_called_once()
            dependency_review.assert_called_once()
            self.assertEqual(security_runner.call_args.args[1], "javascript")
            self.assertEqual(dependency_review.call_args.args[1], "javascript")
            self.assertEqual(code, 3, stderr.getvalue())
            generated = (output / "main.js").read_text(encoding="utf-8")
            self.assertIn("let y = (x * 7);", generated)
            self.assertIn("console.log(y);", generated)
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "python")
            self.assertEqual(report["target_language"], "javascript")
            self.assertEqual(report["validation_gates"]["target_build"], "BLOCKED")
            self.assertIn("No source code is sent", report["note"])

    def test_deterministic_strategy_still_rejects_unsupported_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            output = root / "out"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "ruby", "--output", str(output), "--strategy", "deterministic",
                ])
            self.assertEqual(code, 2)
            self.assertIn("supports --from python --to go", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
