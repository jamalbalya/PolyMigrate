"""CLI integration tests for the deterministic JavaScript-to-Python subset."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


class DeterministicJavaScriptPythonCLITests(unittest.TestCase):
    def test_migration_runs_python_validation_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text(
                'const count = 6;\nconsole.log(count * 7);\n', encoding="utf-8",
            )
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "javascript",
                    "--to", "python", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            generated = output / "main.py"
            self.assertTrue(generated.is_file())
            self.assertIn("print(", generated.read_text(encoding="utf-8"))
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "javascript")
            self.assertEqual(report["target_language"], "python")
            self.assertEqual(report["validation_gates"]["target_build"], "PASSED")
            self.assertEqual(report["validation_gates"]["security_review"], "INCOMPLETE")
            self.assertIn("Deterministic JavaScript-to-Python subset", " ".join(report["warnings"]))

    def test_deterministic_strategy_rejects_unsupported_javascript_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text("console.log('hello');\n", encoding="utf-8")
            output = root / "out"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "javascript",
                    "--to", "php", "--output", str(output), "--strategy", "deterministic",
                ])
            self.assertEqual(code, 2)
            self.assertIn("deterministic strategy currently supports", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
