"""CLI integration tests for the bounded deterministic JavaScript-to-Go subset."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch
from pathlib import Path

from polymigrate.cli import main


class DeterministicJavaScriptGoCLITests(unittest.TestCase):
    def test_migration_runs_offline_and_writes_unverified_go_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text(
                "const count = 6;\nconsole.log(count * 7);\n", encoding="utf-8",
            )
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "javascript",
                    "--to", "go", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            generated = output / "main.go"
            self.assertTrue(generated.is_file())
            self.assertIn("fmt.Println", generated.read_text(encoding="utf-8"))
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "javascript")
            self.assertEqual(report["target_language"], "go")
            self.assertIn("JavaScript-to-Go", " ".join(report["warnings"]))

    def test_deterministic_strategy_rejects_unsupported_javascript_syntax(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text("function main() { return 42; }\n", encoding="utf-8")
            output = root / "out"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "javascript",
                    "--to", "go", "--output", str(output), "--strategy", "deterministic",
                ])
            self.assertEqual(code, 2)
            self.assertIn("Unsupported JavaScript", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
