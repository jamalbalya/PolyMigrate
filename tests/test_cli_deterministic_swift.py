"""CLI tests for deterministic Python-to-Swift migration."""
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


@unittest.skipUnless(os.environ.get("POLYMIGRATE_RUN_SWIFT_E2E") == "1" and shutil.which("swiftc"), "Run in the dedicated Swift CI job")
class DeterministicPythonSwiftCLITests(unittest.TestCase):
    def test_migration_generates_and_runs_swift_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("x = 6\ny = x * 7\nif y > 40:\n    y = 42\nelse:\n    y = 0\nprint(y)\nfor i in range(3):\n    print(i)\n", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "swift", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            self.assertTrue((output / "main.swift").is_file())
            generated = (output / "main.swift").read_text(encoding="utf-8")
            self.assertIn("if (y > 40) {", generated)
            self.assertIn("y = 42", generated)
            self.assertIn("for i in stride(from: Int32(0), to: Int32(3), by: Int(1)) {", generated)
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["target_language"], "swift")
            self.assertEqual(report["validation_gates"]["target_build"], "PASSED")
            self.assertTrue(any(
                item["command_id"] == "target_runtime_smoke" and item["status"] == "PASSED"
                for item in report["validation_results"]["executions"]
            ))


if __name__ == "__main__":
    unittest.main()
