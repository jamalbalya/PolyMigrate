"""CLI integration tests."""
import json
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from contextlib import redirect_stderr, redirect_stdout

from polymigrate.cli import main


class CLITests(unittest.TestCase):
    def test_plan_command_writes_json_outside_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text("print('hi')", encoding="utf-8")
            output = Path(tmp) / "output"
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["plan", "--source", str(root), "--from", "python",
                             "--to", "go", "--output", str(output)])
            self.assertEqual(code, 0)
            plan_path = output / "migration-plan.json"
            self.assertTrue(plan_path.is_file())
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_language"], "python")
            self.assertEqual(payload["target_language"], "go")
            self.assertIn("plan only", " ".join(payload["warnings"]))

    def test_invalid_source_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main(["plan", "--source", str(Path(tmp) / "missing"),
                             "--from", "python", "--to", "go", "--output", str(output)])
            self.assertEqual(code, 2)
            self.assertIn("Source directory does not exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
