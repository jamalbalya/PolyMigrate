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

    def test_if_elif_else_and_string_equality(self):
        source = 'value = "two"\nif value == "one":\n    print("first")\nelif value == "two":\n    print("second")\nelse:\n    print("other")\n'
        code = self._translate(source)
        self.assertIn('value.equals("one")', code)
        self.assertIn('} else if (value.equals("two")) {', code)
        self.assertIn('System.out.println("second");', code)

    def test_boolean_compound_conditions_and_integer_truthiness(self):
        code = self._translate('flag = True\nx = 2\nif flag and x:\n    print("yes")\n')
        self.assertIn("&&", code)
        self.assertIn("(x != 0)", code)

    def test_rejects_chained_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Chained comparisons"):
            self._translate('x = 2\nif 0 < x < 4:\n    print("yes")\n')

    def test_rejects_assignments_inside_conditional_bodies(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "only print"):
            self._translate("x = 1\nif x > 0:\n    y = 2\nprint(x)\n")

    def test_rejects_conditional_chains_over_twenty_branches(self):
        lines = ["x = 0", "if x == 0:", "    print('match')"]
        for value in range(1, 21):
            lines.extend([f"elif x == {value}:", "    print('match')"])
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "20 branches"):
            self._translate("\n".join(lines) + "\n")

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_generated_java_condition_compiles_and_matches_expected_output(self):
        source = 'value = "two"\nif value == "one":\n    print("first")\nelif value == "two":\n    print("second")\nelse:\n    print("other")\n'
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
            self.assertEqual(executed.stdout, "second\n")

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
