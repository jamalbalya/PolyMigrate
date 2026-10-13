"""CLI integration tests for deterministic Python-to-PHP migration."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


class DeterministicPythonPHPCLITests(unittest.TestCase):
    def test_migration_generates_php_without_initializing_ai(self):
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
                    "--to", "php", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            generated = (output / "main.php").read_text(encoding="utf-8")
            self.assertTrue(generated.startswith("<?php"))
            self.assertIn("$y = ($x * 7);", generated)
            self.assertIn("echo implode(' ', array_map('polymigrateString', [$y])) . PHP_EOL;", generated)
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "python")
            self.assertEqual(report["target_language"], "php")
            self.assertEqual(report["validation_gates"]["target_build"], "BLOCKED")
            self.assertIn("No source code is sent", report["note"])

    def test_go_to_php_pair_is_supported_by_deterministic_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text("""package main
import "fmt"
func main() {
    fmt.Println(7)
}
""", encoding="utf-8")
            output = root / "out"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "go",
                    "--to", "php", "--output", str(output), "--strategy", "deterministic",
                ])
            self.assertEqual(code, 3, stderr.getvalue())
            self.assertTrue((output / "main.php").is_file())
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["source_language"], "go")
            self.assertEqual(report["target_language"], "php")
            self.assertIn("Go-to-PHP", " ".join(report["warnings"]))


if __name__ == "__main__":
    unittest.main()
