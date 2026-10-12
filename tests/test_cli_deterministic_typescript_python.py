"""CLI integration tests for deterministic TypeScript-to-Python migration."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.cli import main


class DeterministicTypeScriptPythonCLITests(unittest.TestCase):
    def test_migration_generates_python_without_initializing_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.ts").write_text(
                'const count: number = 6;\nconsole.log(count * 7);\n', encoding="utf-8",
            )
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as provider_setup, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "typescript",
                    "--to", "python", "--output", str(output), "--strategy", "deterministic",
                ])
            provider_setup.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            generated = output / "main.py"
            self.assertTrue(generated.is_file())
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["source_language"], "typescript")
            self.assertEqual(report["target_language"], "python")
            self.assertEqual(report["validation_gates"]["target_build"], "PASSED")
            self.assertEqual(report["validation_gates"]["security_review"], "INCOMPLETE")
            runtime = next(
                item for item in report["validation_results"]["executions"]
                if item["command_id"] == "target_runtime_smoke_python"
            )
            self.assertEqual(runtime["stdout"], "42\n")


if __name__ == "__main__":
    unittest.main()
