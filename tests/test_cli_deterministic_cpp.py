"""CLI integration tests for deterministic Python-to-C++ migration."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


class DeterministicPythonCppCLITests(unittest.TestCase):
    def test_migration_generates_cpp_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("x = 6\nprint(x)\n", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 patch("polymigrate.cli.shutil.which", return_value=None), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "cpp", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            generated = (output / "main.cpp").read_text(encoding="utf-8")
            self.assertIn("std::int32_t x = 6;", generated)
            self.assertIn("std::cout << polymigrate_string(x);", generated)
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "python")
            self.assertEqual(report["target_language"], "cpp")
            self.assertEqual(report["validation_gates"]["target_build"], "BLOCKED")
            self.assertIn("No source code is sent", report["note"])

    def test_deterministic_strategy_still_rejects_unsupported_source_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text("package main\n", encoding="utf-8")
            output = root / "out"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "go",
                    "--to", "go", "--output", str(output), "--strategy", "deterministic",
                ])
            self.assertEqual(code, 2)
            self.assertIn("deterministic strategy currently supports", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
