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

    def test_not_expression_preserves_python_truthiness(self):
        code = self._translate("flag = not False\nx = 0\nprint(flag)\nprint(not x)\n")
        self.assertIn("!(false)", code)
        self.assertIn("!((x != 0))", code)

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_not_expression_matches_python_output(self):
        code = self._translate("flag = not False\nx = 0\nprint(flag)\nprint(not x)\n")
        with tempfile.TemporaryDirectory() as tmp:
            java_file = Path(tmp) / "Main.java"
            java_file.write_text(code, encoding="utf-8")
            compiled = subprocess.run(["javac", str(java_file)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run(["java", "-cp", tmp, "Main"], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "True\nTrue\n")

    def test_conditional_assignments_to_existing_variables(self):
        code = self._translate("x = 1\nif x > 0:\n    x = 2\nelse:\n    x = 3\nprint(x)\n")
        self.assertIn("x = 2;", code)
        self.assertIn("x = 3;", code)

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_conditional_assignments_match_python_output(self):
        code = self._translate("x = 1\nif x > 0:\n    x = 2\nelse:\n    x = 3\nprint(x)\n")
        with tempfile.TemporaryDirectory() as tmp:
            java_file = Path(tmp) / "Main.java"
            java_file.write_text(code, encoding="utf-8")
            compiled = subprocess.run(["javac", str(java_file)], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            run = subprocess.run(["java", "-cp", tmp, "Main"], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "2\n")

    def test_translates_assignments_arithmetic_and_print(self):
        code = self._translate("x = 6\ny = x * 7\nprint(y)\n")
        self.assertIn("int x = 6;", code)
        self.assertIn("int y = (x * 7);", code)
        self.assertIn("System.out.println(y);", code)

    def test_print_supports_multiple_arguments_and_empty_call(self):
        code = self._translate('print(42, "hello", True)\nprint()\n')
        self.assertIn('Integer.toString(42) + " " + "hello" + " " + ((true) ? "True" : "False")', code)
        self.assertIn("System.out.println();", code)

    def test_print_rejects_keyword_arguments_and_too_many_values(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "keyword arguments"):
            self._translate('print("a", sep=",")\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "32 positional"):
            self._translate("print(" + ", ".join("1" for _ in range(33)) + ")\n")

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_multi_argument_print_compiles_and_matches_python_output(self):
        code = self._translate('print(42, "hello", True)\nprint()\n')
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
            self.assertEqual(executed.stdout, "42 hello True\n\n")

    def test_abs_builtin_supports_safe_integer_values(self):
        code = self._translate("x = -42\nprint(abs(x))\nprint(abs(7))\n")
        self.assertIn("Math.abs(x)", code)
        self.assertIn("Math.abs(7)", code)

    def test_abs_builtin_rejects_shadowing_invalid_types_and_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the abs"):
            self._translate('abs = 1\nprint(abs(2))\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the abs"):
            self._translate('print(abs(2))\nabs = 1\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "integer values"):
            self._translate('print(abs(True))\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one positional"):
            self._translate("print(abs(value=2))\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed int32 range"):
            self._translate("print(abs(-2147483648))\n")

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_abs_builtin_generated_java_matches_python_output(self):
        code = self._translate("x = -42\nprint(abs(x))\nprint(abs(7))\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            java_file = root / "Main.java"
            java_file.write_text(code, encoding="utf-8")
            compiled = subprocess.run(["javac", str(java_file)], capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            executed = subprocess.run(["java", "-cp", tmp, "Main"], capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(executed.returncode, 0, executed.stderr)
            self.assertEqual(executed.stdout, "42\n7\n")

    def test_str_builtin_converts_integer_and_boolean_to_python_text(self):
        code = self._translate('x = 42\nprint("value=" + str(x))\nprint(str(True))\n')
        self.assertIn("Integer.toString(x)", code)
        self.assertIn('((true) ? "True" : "False")', code)

    def test_str_builtin_cannot_be_shadowed_or_called_with_keywords(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the str"):
            self._translate('str = "shadowed"\nprint(str(2))\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the str"):
            self._translate('print(str(2))\nstr = "shadowed"\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one positional"):
            self._translate("print(str(value=2))\n")

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_str_builtin_generated_java_compiles_and_matches_output(self):
        source = 'x = 42\nprint("value=" + str(x))\nprint(str(True))\n'
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
            self.assertEqual(executed.stdout, "value=42\nTrue\n")

    def test_string_concatenation_and_escaping(self):
        code = self._translate('message = "hello\\\\nworld"\nprint(message)\n')
        self.assertIn(r'"hello\\nworld"', code)
        self.assertIn("String message =", code)

    def test_boolean_output_preserves_python_spelling(self):
        code = self._translate("flag = True\nprint(flag)\n")
        self.assertIn('System.out.println((flag) ? "True" : "False");', code)

    def test_rejects_unsupported_while_loop(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Unsupported statement syntax"):
            self._translate('while True:\n    print("yes")\n')

    def test_rejects_integer_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed int32 range"):
            self._translate("x = 2147483647\ny = x + 1\nprint(y)\n")

    def test_rejects_type_changes(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Changing the type"):
            self._translate('x = 1\nx = "one"\nprint(x)\n')

    def test_range_loop_generation_and_bounds(self):
        code = self._translate("for i in range(3):\n    print(i)\n")
        self.assertIn("for (int i = 0; i < 3; i++) {", code)
        self.assertIn("System.out.println(i);", code)

    def test_negative_range_step_generation(self):
        code = self._translate("for i in range(3, 0, -1):\n    print(i)\n")
        self.assertIn("for (int i = 3; i > 0; i--) {", code)

    def test_rejects_zero_range_step(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "step cannot be zero"):
            self._translate("for i in range(0, 3, 0):\n    print(i)\n")

    def test_rejects_range_over_10000_iterations(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000-iteration"):
            self._translate("for i in range(10001):\n    print(i)\n")

    def test_rejects_loop_variable_shadowing(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "cannot shadow"):
            self._translate("i = 1\nfor i in range(3):\n    print(i)\nprint(i)\n")

    def test_rejects_for_else(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "for/else"):
            self._translate("for i in range(3):\n    print(i)\nelse:\n    print('done')\n")

    def test_rejects_assignments_in_loop_body(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "only print"):
            self._translate("for i in range(3):\n    x = i\n")

    @unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "JDK is required")
    def test_generated_java_range_loop_compiles_and_matches_expected_output(self):
        source = "for i in range(3):\n    print(i)\n"
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
            self.assertEqual(executed.stdout, "0\n1\n2\n")

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
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "previously assigned variables"):
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
