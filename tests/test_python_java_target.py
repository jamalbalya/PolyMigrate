"""Tests for the deterministic Python-to-Java subset."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.python_java_target import PythonToJavaTargetAdapter, UnsupportedPythonSyntax


class PythonToJavaTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            artifacts = PythonToJavaTargetAdapter().generate(project, {})
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].relative_path, "Main.java")
        return artifacts[0].content

    def test_translates_assignments_arithmetic_and_print(self):
        code = self._translate("x = 6\ny = x * 7\nprint(y)\n")
        self.assertIn("int x = 6;", code)
        self.assertIn("int y = (x * 7);", code)
        self.assertIn("System.out.println(y);", code)

    def test_string_concatenation_and_escaping(self):
        code = self._translate('message = "hello\\\\nworld"\nprint(message)\n')
        self.assertIn(r'"hello\\nworld"', code)
        self.assertIn("String message =", code)

    def test_boolean_output_preserves_python_spelling(self):
        code = self._translate("flag = True\nprint(flag)\n")
        self.assertIn('System.out.println((flag) ? "True" : "False");', code)

    def test_rejects_control_flow_instead_of_guessing(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Unsupported statement syntax"):
            self._translate('if True:\n    print("yes")\n')

    def test_rejects_loops(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Unsupported statement syntax"):
            self._translate("for i in range(3):\n    print(i)\n")

    def test_rejects_integer_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed int32 range"):
            self._translate("x = 2147483647\ny = x + 1\nprint(y)\n")

    def test_rejects_type_changes(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Changing the type"):
            self._translate('x = 1\nx = "one"\nprint(x)\n')

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_generated_java_compiles_and_matches_expected_output(self):
        source = 'message = "hello\\\\nworld"\nprint(message)\n'
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            java_file = root / "Main.java"
            java_file.write_text(code, encoding="utf-8")
            compiled = subprocess.run(
                ["javac", str(java_file)], capture_output=True, text=True, timeout=30, check=False
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run(
                ["java", "-cp", tmp, "Main"], capture_output=True, text=True, timeout=30, check=False
            )
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertEqual(executed.stdout, "hello\\nworld\n")


if __name__ == "__main__":
    unittest.main()
