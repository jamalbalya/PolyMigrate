"""CLI tests for deterministic Python-to-Rust migration."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


class DeterministicPythonRustCLITests(unittest.TestCase):
    def test_migration_generates_cargo_project_without_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("x = 6\ny = x * 7\nprint(y)\n", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 patch("polymigrate.cli.shutil.which", return_value=None), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "rust", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            self.assertTrue((output / "Cargo.toml").is_file())
            self.assertIn("println!", (output / "src" / "main.rs").read_text(encoding="utf-8"))
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["target_language"], "rust")
            self.assertEqual(report["validation_gates"]["target_build"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
