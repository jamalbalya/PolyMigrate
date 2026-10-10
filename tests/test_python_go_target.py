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

    def test_rejects_if_statement(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "If"):
            self._translate("if True:\n    print('yes')\n")

    def test_rejects_multiple_print_arguments(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one"):
            self._translate('print("hello", "world")\n')

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
