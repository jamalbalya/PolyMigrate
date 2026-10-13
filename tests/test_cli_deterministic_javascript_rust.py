"""CLI integration tests for deterministic JavaScript-to-Rust migration."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


class DeterministicJavaScriptRustCLITests(unittest.TestCase):
    def test_migration_generates_cargo_project_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text('''const count = 6;
console.log("value=", count * 7);
''', encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "javascript",
                    "--to", "rust", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            self.assertTrue((output / "Cargo.toml").is_file())
            self.assertTrue((output / "src" / "main.rs").is_file())
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "javascript")
            self.assertEqual(report["target_language"], "rust")
            self.assertIn("JavaScript-to-Rust", " ".join(report["warnings"]))


if __name__ == "__main__":
    unittest.main()
