"""Tests for the deterministic Python-to-JavaScript adapter."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.python_javascript_target import (
    PythonToJavaScriptTargetAdapter,
    UnsupportedPythonSyntax,
)


class PythonToJavaScriptTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            artifacts = PythonToJavaScriptTargetAdapter().generate(project, {})
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].relative_path, "main.js")
        return artifacts[0].content

    def test_print_string(self):
        self.assertIn('console.log("hello");', self._translate('print("hello")\n'))

    def test_variables_and_arithmetic(self):
        code = self._translate("x = 6\ny = x * 7\nprint(y)\n")
        self.assertIn("let x = 6;", code)
        self.assertIn("let y = (x * 7);", code)
        self.assertIn("console.log(y);", code)

    def test_string_concatenation(self):
        code = self._translate('greeting = "hello" + " world"\nprint(greeting)\n')
        self.assertIn('let greeting = ("hello" + " world");', code)

    def test_rejects_unsafe_integer_arithmetic(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "safe integer range"):
            self._translate("x = 9007199254740991\ny = x + 1\nprint(y)\n")

    def test_rejects_undefined_names(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "used before assignment"):
            self._translate("print(missing)\n")

    def test_rejects_unsupported_control_flow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "If"):
            self._translate("if True:\n    print('yes')\n")

    def test_rejects_unused_variables(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "never used"):
            self._translate("x = 1\nprint(42)\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_generated_program_passes_syntax_check_and_runs(self):
        code = self._translate("x = 6\ny = x * 7\nprint(y)\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            check = subprocess.run(["node", "--check", str(path)], capture_output=True,
                                   text=True, timeout=10, check=False)
            self.assertEqual(check.returncode, 0, check.stderr)
            run = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                 timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "42\n")


if __name__ == "__main__":
    unittest.main()
