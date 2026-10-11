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

    def test_print_multiple_arguments_and_empty_call(self):
        code = self._translate('print(42, "hello", True)\nprint()\n')
        self.assertIn('console.log([String(42), "hello", (true ? "True" : "False")].join(" "));', code)
        self.assertIn('console.log([].join(" "));', code)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_multi_argument_print_matches_python_output(self):
        code = self._translate('print(42, "hello", True)\nprint()\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            checked = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            run = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "42 hello True\n\n")

    def test_print_rejects_keywords_and_too_many_arguments(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "keyword arguments"):
            self._translate('print("a", sep=",")\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "32 positional"):
            self._translate("print(" + ", ".join("1" for _ in range(33)) + ")\n")

    def test_str_builtin_converts_integer_and_boolean(self):
        code = self._translate('x = 42\nprint("value=" + str(x))\nprint(str(True))\n')
        self.assertIn("String(x)", code)
        self.assertIn('(true ? "True" : "False")', code)

    def test_str_builtin_rejects_shadowing_and_keyword_arguments(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the str"):
            self._translate('str = "shadowed"\nprint(str(2))\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the str"):
            self._translate('print(str(2))\nstr = "shadowed"\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one positional"):
            self._translate("print(str(value=2))\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_str_builtin_generated_javascript_matches_python_output(self):
        code = self._translate('x = 42\nprint("value=" + str(x))\nprint(str(True))\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            run = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value=42\nTrue\n")

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

    def test_normalizes_negative_zero_to_preserve_python_print_output(self):
        self.assertIn("console.log(0);", self._translate("print(-0)\n"))

    def test_if_else_comparison_is_translated_and_executes(self):
        source = 'x = 6\nif x > 0:\n    print("positive")\nelse:\n    print("non-positive")\n'
        code = self._translate(source)
        self.assertIn("if ((x > 0)) {", code)
        self.assertIn("} else {", code)

    def test_compound_conditions_are_translated(self):
        code = self._translate('x = 6\nif x > 0 and x < 10:\n    print("in range")\n')
        self.assertIn("&&", code)

    def test_rejects_conditional_chains_over_twenty_branches(self):
        lines = ["x = 0", "if x == 0:", "    print('match')"]
        for value in range(1, 21):
            lines.extend([f"elif x == {value}:", "    print('match')"])
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "20 branches"):
            self._translate("\n".join(lines) + "\n")

    def test_rejects_chained_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Chained comparisons"):
            self._translate('x = 6\nif 0 < x < 10:\n    print("in range")\n')

    def test_rejects_assignment_inside_conditional(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "only print"):
            self._translate("x = 1\nif x > 0:\n    y = 2\nprint(x)\n")

    def test_rejects_string_ordering_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "String ordering"):
            self._translate('if "b" > "a":\n    print("ordered")\n')

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_if_else_generated_program_matches_python_output(self):
        source = 'x = 6\nif x > 0:\n    print("positive")\nelse:\n    print("non-positive")\n'
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            run = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                 timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "positive\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_elif_chain_generated_program_matches_python_output(self):
        source = 'x = 2\nif x == 1:\n    print("one")\nelif x == 2:\n    print("two")\nelse:\n    print("other")\n'
        code = self._translate(source)
        self.assertIn("else if", code)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            run = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                 timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "two\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_boolean_literals_and_output_match_python(self):
        source = 'flag = True\nother = False\nif flag and not other:\n    print("condition")\nprint(flag)\nprint(other)\nif flag == True:\n    print("equal")\n'
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            run = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                 timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "condition\nTrue\nFalse\nequal\n")

    def test_boolean_arithmetic_and_ordering_are_rejected(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Boolean arithmetic"):
            self._translate("flag = True\nprint(flag + True)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Boolean ordering"):
            self._translate('flag = True\nif flag < False:\n    print("no")\n')

    def test_range_loop_is_translated(self):
        code = self._translate("for i in range(3):\n    print(i)\n")
        self.assertIn("for (let i = 0; i < 3; i++) {", code)
        self.assertIn("console.log(i);", code)

    def test_range_loop_uses_statically_known_bounds(self):
        code = self._translate("start = 1\nstop = 4\nfor i in range(start, stop):\n    print(i)\n")
        self.assertIn("for (let i = start; i < stop; i++) {", code)

    def test_range_steps_are_bounded_and_zero_is_rejected(self):
        code = self._translate("for i in range(0, 5, 2):\n    print(i)\n")
        negative_code = self._translate("for i in range(5, 0, -2):\n    print(i)\n")
        self.assertIn("i += 2", code)
        self.assertIn("i > 0", negative_code)
        self._translate("for i in range(0, 10001, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "step cannot be zero"):
            self._translate("for i in range(0, 5, 0):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "overflow the target integer range"):
            self._translate("for i in range(9007199254740990, 9007199254740991, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000-iteration"):
            self._translate("for i in range(0, 20002, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000-iteration"):
            self._translate("for i in range(10001):\n    print(i)\n")

    def test_rejects_loop_variable_shadowing(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "cannot shadow"):
            self._translate("i = 1\nfor i in range(3):\n    print(i)\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_signed_range_steps_generated_program_matches_python_output(self):
        source = "for i in range(0, 5, 2):\n    print(i)\nfor j in range(5, 0, -2):\n    print(j)\n"
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            run = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                 timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "0\n2\n4\n5\n3\n1\n")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_range_loop_generated_program_matches_python_output(self):
        code = self._translate("for i in range(3):\n    print(i)\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.js"
            path.write_text(code, encoding="utf-8")
            run = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                 timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "0\n1\n2\n")

    def test_rejects_unsafe_integer_arithmetic(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "safe integer range"):
            self._translate("x = 9007199254740991\ny = x + 1\nprint(y)\n")

    def test_rejects_undefined_names(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "used before assignment"):
            self._translate("print(missing)\n")

    def test_rejects_unsupported_control_flow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "While"):
            self._translate("while True:\n    print('yes')\n")

    def test_rejects_console_shadowing_when_print_is_used(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "conflicts with the console.log"):
            self._translate('console = "shadow"\nprint("hello")\n')

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
