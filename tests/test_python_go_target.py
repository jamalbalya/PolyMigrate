"""Tests for the deterministic Python-to-Go adapter."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.python_go_target import (
    PythonToGoTargetAdapter,
    UnsupportedPythonSyntax,
)


class PythonToGoTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter(
                "python", (".py",)
            ).analyze(root)
            artifacts = PythonToGoTargetAdapter().generate(project, {})

        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].relative_path, "main.go")
        return artifacts[0].content

    def test_print_multiple_arguments_and_empty_call(self):
        code = self._translate('print(42, "hello", True)\nprint()\n')
        self.assertIn('fmt.Println(42, "hello", map[bool]string{true: "True", false: "False"}[true])', code)
        self.assertIn("fmt.Println()", code)

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_multi_argument_print_matches_python_output(self):
        code = self._translate('print(42, "hello", True)\nprint()\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            formatted = subprocess.run(["gofmt", "-w", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(formatted.returncode, 0, formatted.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "42 hello True\n\n")

    def test_print_rejects_keywords_and_too_many_arguments(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "keyword arguments"):
            self._translate('print("a", sep=",")\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "32 positional"):
            self._translate("print(" + ", ".join("1" for _ in range(33)) + ")\n")

    def test_str_builtin_converts_integer_and_boolean(self):
        code = self._translate('x = 42\nprint("value=" + str(x))\nprint(str(True))\n')
        self.assertIn("fmt.Sprint(x)", code)
        self.assertIn('map[bool]string{true: "True", false: "False"}[true]', code)

    def test_str_builtin_rejects_shadowing_and_keyword_arguments(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the str"):
            self._translate('str = "shadowed"\nprint(str(2))\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the str"):
            self._translate('print(str(2))\nstr = "shadowed"\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one positional"):
            self._translate("print(str(value=2))\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_str_builtin_generated_go_matches_python_output(self):
        code = self._translate('x = 42\nprint("value=" + str(x))\nprint(str(True))\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value=42\nTrue\n")

    def test_abs_builtin_supports_safe_integer_values(self):
        code = self._translate("x = -42\nprint(abs(x))\nprint(abs(7))\n")
        self.assertIn("polymigrateAbsInt32(x)", code)
        self.assertIn("func polymigrateAbsInt32(value int) int", code)

    def test_abs_builtin_rejects_shadowing_invalid_types_and_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the abs"):
            self._translate('abs = 1\nprint(abs(2))\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Shadowing the abs"):
            self._translate('print(abs(2))\nabs = 1\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "integer values"):
            self._translate('print(abs(True))\n')
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one positional"):
            self._translate("print(abs(value=2))\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "portable Go int32 range"):
            self._translate("print(abs(-2147483648))\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "generated abs helper name"):
            self._translate("polymigrateAbsInt32 = 1\nprint(abs(2), polymigrateAbsInt32)\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_abs_builtin_generated_go_matches_python_output(self):
        code = self._translate("x = -42\nprint(abs(x))\nprint(abs(7))\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "42\n7\n")

    def test_not_expression_preserves_python_truthiness(self):
        code = self._translate("flag = not False\nx = 0\nprint(flag)\nprint(not x)\n")
        self.assertIn("!(false)", code)
        self.assertIn("!((x != 0))", code)

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_not_expression_matches_python_output(self):
        code = self._translate("flag = not False\nx = 0\nprint(flag)\nprint(not x)\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True, text=True, timeout=30)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "True\nTrue\n")

    def test_print_string(self):
        code = self._translate('print("hello")\n')
        self.assertIn('import "fmt"', code)
        self.assertIn('fmt.Println("hello")', code)

    def test_variables_and_arithmetic(self):
        code = self._translate("x = 6\ny = x * 7\nprint(y)\n")
        self.assertIn("x := 6", code)
        self.assertIn("y := (x * 7)", code)
        self.assertIn("fmt.Println(y)", code)

    def test_rejects_positive_integer_overflow(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "portable Go int32 range"
        ):
            self._translate(
                "x = 2147483647\ny = x + 1\nprint(y)\n"
            )

    def test_rejects_negative_integer_underflow(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "portable Go int32 range"
        ):
            self._translate(
                "x = -2147483647\ny = x - 2\nprint(y)\n"
            )

    def test_rejects_integer_literal_outside_portable_range(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "portable Go int32 range"
        ):
            self._translate("print(2147483648)\n")

    def test_accepts_integer_arithmetic_within_portable_range(self):
        code = self._translate(
            "x = 2147483646\ny = x + 1\nprint(y)\n"
        )
        self.assertIn("y := (x + 1)", code)

    def test_accepts_signed_int32_minimum(self):
        code = self._translate("x = -2147483648\nprint(x)\n")
        self.assertIn("x := -2147483648", code)

    def test_accepts_signed_int32_maximum(self):
        code = self._translate("x = 2147483647\nprint(x)\n")
        self.assertIn("x := 2147483647", code)

    def test_rejects_integer_below_signed_int32_minimum(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "portable Go int32 range"
        ):
            self._translate("print(-2147483649)\n")

    def test_rejects_multiplication_overflow(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "portable Go int32 range"
        ):
            self._translate("x = 1073741824 * 2\nprint(x)\n")

    def test_rejects_negating_signed_int32_minimum(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "portable Go int32 range"
        ):
            self._translate("x = -2147483648\ny = -x\nprint(y)\n")

    def test_string_concatenation(self):
        code = self._translate(
            'greeting = "hello" + " world"\nprint(greeting)\n'
        )
        self.assertIn('greeting := ("hello" + " world")', code)

    def test_rejects_assignment_to_print_builtin(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "conflicts with the supported print"
        ):
            self._translate("print = 1\nprint(2)\n")

    def test_rejects_loop_statement(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "While"):
            self._translate("while True:\n    print('yes')\n")

    def test_if_else_comparison_is_translated(self):
        code = self._translate(
            'x = 6\nif x > 0:\n    print("positive")\nelse:\n    print("non-positive")\n'
        )
        self.assertIn("if (x > 0) {", code)
        self.assertIn("} else {", code)
        self.assertIn('fmt.Println("positive")', code)

    def test_compound_conditions_and_truthiness_are_translated(self):
        code = self._translate(
            'x = 6\nif x and x < 10:\n    print("in range")\n'
        )
        self.assertIn("&&", code)
        self.assertIn("(x != 0)", code)

    def test_rejects_conditional_chains_over_twenty_branches(self):
        lines = ["x = 0", "if x == 0:", "    print('match')"]
        for value in range(1, 21):
            lines.extend([f"elif x == {value}:", "    print('match')"])
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "20 branches"):
            self._translate("\n".join(lines) + "\n")

    def test_rejects_chained_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Chained comparisons"):
            self._translate('x = 6\nif 0 < x < 10:\n    print("in range")\n')

    def test_rejects_assignments_inside_conditionals(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "only print"):
            self._translate("x = 1\nif x > 0:\n    y = 2\nprint(x)\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_if_else_generated_program_builds_and_runs(self):
        code = self._translate(
            'x = 6\nif x > 0:\n    print("positive")\nelse:\n    print("non-positive")\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True,
                                 text=True, timeout=10, check=False)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True,
                                 text=True, timeout=30, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "positive\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_elif_chain_generated_program_matches_python_output(self):
        source = 'x = 2\nif x == 1:\n    print("one")\nelif x == 2:\n    print("two")\nelse:\n    print("other")\n'
        code = self._translate(source)
        self.assertIn("} else if (x == 2) {", code)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True,
                                 text=True, timeout=10, check=False)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True,
                                 text=True, timeout=30, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "two\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_boolean_literals_and_output_match_python(self):
        source = 'flag = True\nother = False\nif flag and not other:\n    print("condition")\nprint(flag)\nprint(other)\nif flag == True:\n    print("equal")\n'
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True,
                                 text=True, timeout=10, check=False)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True,
                                 text=True, timeout=30, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "condition\nTrue\nFalse\nequal\n")

    def test_boolean_arithmetic_and_ordering_are_rejected(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Boolean arithmetic"):
            self._translate("flag = True\nprint(flag + True)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Boolean ordering"):
            self._translate('flag = True\nif flag < False:\n    print("no")\n')

    def test_range_loop_is_translated(self):
        code = self._translate("for i in range(3):\n    print(i)\n")
        self.assertIn("for i := 0; i < 3; i++ {", code)
        self.assertIn("fmt.Println(i)", code)

    def test_range_loop_uses_statically_known_bounds(self):
        code = self._translate("start = 1\nstop = 4\nfor i in range(start, stop):\n    print(i)\n")
        self.assertIn("for i := start; i < stop; i++ {", code)

    def test_range_steps_are_bounded_and_zero_is_rejected(self):
        code = self._translate("for i in range(0, 5, 2):\n    print(i)\n")
        negative_code = self._translate("for i in range(5, 0, -2):\n    print(i)\n")
        self.assertIn("i += 2", code)
        self.assertIn("i > 0", negative_code)
        self._translate("for i in range(0, 10001, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "step cannot be zero"):
            self._translate("for i in range(0, 5, 0):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "overflow the target integer range"):
            self._translate("for i in range(2147483646, 2147483647, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000-iteration"):
            self._translate("for i in range(0, 20002, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000-iteration"):
            self._translate("for i in range(10001):\n    print(i)\n")

    def test_rejects_loop_variable_shadowing(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "cannot shadow"):
            self._translate("i = 1\nfor i in range(3):\n    print(i)\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_signed_range_steps_generated_program_builds_and_runs(self):
        source = "for i in range(0, 5, 2):\n    print(i)\nfor j in range(5, 0, -2):\n    print(j)\n"
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True,
                                 text=True, timeout=10, check=False)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True,
                                 text=True, timeout=30, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "0\n2\n4\n5\n3\n1\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_range_loop_generated_program_builds_and_runs(self):
        code = self._translate("for i in range(3):\n    print(i)\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            path.write_text(code, encoding="utf-8")
            fmt = subprocess.run(["gofmt", "-w", str(path)], capture_output=True,
                                 text=True, timeout=10, check=False)
            self.assertEqual(fmt.returncode, 0, fmt.stderr)
            run = subprocess.run(["go", "run", str(path)], capture_output=True,
                                 text=True, timeout=30, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "0\n1\n2\n")

    def test_multiple_print_arguments_are_supported(self):
        code = self._translate('print("hello", "world")\n')
        self.assertIn('fmt.Println("hello", "world")', code)

    def test_rejects_undefined_name(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "used before assignment"
        ):
            self._translate("print(missing)\n")

    def test_rejects_division(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "Unsupported expression"
        ):
            self._translate("print(7 / 2)\n")

    def test_rejects_variable_type_change(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Changing the type"):
            self._translate('x = 1\nx = "text"\n')

    def test_rejects_fmt_variable_when_print_is_used(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "conflicts with"):
            self._translate('fmt = "shadow"\nprint("hello")\n')

    def test_rejects_python_placeholder_with_explicit_message(self):
        with self.assertRaisesRegex(
            UnsupportedPythonSyntax, "placeholder is not supported"
        ):
            self._translate("_ = 1\nprint(2)\n")

    def test_rejects_unused_variable(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "never used"):
            self._translate("x = 1\nprint(42)\n")

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_generated_program_builds_and_runs(self):
        code = self._translate("x = 6\ny = x * 7\nprint(y)\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.go"
            binary = Path(tmp) / "program"
            path.write_text(code, encoding="utf-8")

            fmt = subprocess.run(
                ["gofmt", "-w", str(path)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(fmt.returncode, 0, fmt.stderr)

            env = {
                **os.environ,
                "GOTOOLCHAIN": "local",
                "GO111MODULE": "off",
            }
            build = subprocess.run(
                ["go", "build", "-o", str(binary), str(path)],
                capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(build.returncode, 0, build.stderr)

            run = subprocess.run(
                [str(binary)], capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "42\n")


if __name__ == "__main__":
    unittest.main()
