"""Tests for the constrained deterministic Python-to-Ruby translator."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.pipeline import SourceProject, SourceUnit
from polymigrate.migration.python_ruby_target import PythonToRubyTargetAdapter, UnsupportedPythonSyntax


def project_for(source: str, path: str = "main.py") -> SourceProject:
    return SourceProject(
        Path("."),
        "python",
        (SourceUnit(path, source, hashlib.sha256(source.encode("utf-8")).hexdigest()),),
    )


class PythonToRubyTranslatorTests(unittest.TestCase):
    def test_translates_assignments_arithmetic_and_positional_print(self):
        generated = PythonToRubyTargetAdapter().generate(
            project_for("x = 6\ny = x * 7\nprint(y)\n"), {}
        )[0]
        self.assertEqual(generated.relative_path, "main.rb")
        self.assertIn("x = 6", generated.content)
        self.assertIn("y = (x * 7)", generated.content)
        self.assertIn("puts [y].map { |value| polymigrate_string(value) }.join(' ')", generated.content)
        self.assertIn("def polymigrate_string(value)", generated.content)

    def test_preserves_python_boolean_text_and_string_concatenation(self):
        generated = PythonToRubyTargetAdapter().generate(
            project_for("prefix = 'hello ' + 'world'\nflag = True\nprint(prefix, flag, str(False))\n"), {}
        )[0].content
        self.assertIn("prefix = ('hello ' + 'world')", generated)
        self.assertIn("flag = true", generated)
        self.assertIn("polymigrate_string(false)", generated)
        self.assertIn("return 'True' if value == true", generated)
        self.assertIn("return 'False' if value == false", generated)

    def test_translates_nested_source_paths_without_flattening_them(self):
        generated = PythonToRubyTargetAdapter().generate(
            project_for("print('module')\n", "src/module.py"), {}
        )[0]
        self.assertEqual(generated.relative_path, "src/module.rb")

    def test_rejects_branch_assignments_and_chained_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "bodies may contain only print"):
            PythonToRubyTargetAdapter().generate(
                project_for("value = 1\nif value:\n    value = 2\nprint(value)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Chained comparisons"):
            PythonToRubyTargetAdapter().generate(
                project_for("value = 1\nif 0 < value < 2:\n    print(value)\n"), {}
            )

    def test_rejects_ruby_reserved_and_uppercase_local_names(self):
        for name in ("end", "self", "API_KEY"):
            with self.subTest(name=name), self.assertRaisesRegex(UnsupportedPythonSyntax, "not a supported Ruby local variable"):
                PythonToRubyTargetAdapter().generate(
                    project_for(f"{name} = 1" + chr(10) + f"print({name})" + chr(10)), {}
                )

    def test_rejects_signed_32_bit_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed 32-bit range"):
            PythonToRubyTargetAdapter().generate(
                project_for("value = 2147483647 + 1\nprint(value)\n"), {}
            )

    def test_translates_conditionals_and_python_string_truthiness(self):
        generated = PythonToRubyTargetAdapter().generate(
            project_for("text = '0'\nif text:\n    print('truthy')\nelse:\n    print('falsey')\n"), {}
        )[0].content
        self.assertIn("if (text != '')", generated)
        self.assertIn("else", generated)
        self.assertIn("end", generated)

    def test_rejects_zero_step_and_excessive_range(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "step cannot be zero"):
            PythonToRubyTargetAdapter().generate(
                project_for("for i in range(1, 5, 0):\n    print(i)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000 actual iterations"):
            PythonToRubyTargetAdapter().generate(
                project_for("for i in range(10001):\n    print(i)\n"), {}
            )

    def test_rejects_range_counter_overflow_and_boolean_bounds(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "counter could overflow"):
            PythonToRubyTargetAdapter().generate(
                project_for("for i in range(2147483646, 2147483647, 2):\n    print(i)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "arguments must be integers"):
            PythonToRubyTargetAdapter().generate(
                project_for("for i in range(True):\n    print(i)\n"), {}
            )

    def test_negative_step_range_loop_runs_with_python_semantics(self):
        ruby = shutil.which("ruby")
        if ruby is None:
            self.skipTest("Ruby CLI is not installed in this test environment")
        generated = PythonToRubyTargetAdapter().generate(
            project_for("for i in range(3, 0, -1):\n    print(i)\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / generated.relative_path
            path.write_text(generated.content, encoding="utf-8")
            run = subprocess.run([ruby, str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "3\n2\n1\n")

    def test_zero_iteration_range_does_not_define_loop_variable(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "used before assignment"):
            PythonToRubyTargetAdapter().generate(
                project_for("for i in range(0):\n    print(i)\nprint(i)\n"), {}
            )

    def test_generated_ruby_runs_when_ruby_is_installed(self):
        ruby = shutil.which("ruby")
        if ruby is None:
            self.skipTest("Ruby CLI is not installed in this test environment")
        generated = PythonToRubyTargetAdapter().generate(
            project_for("prefix = 'value='\nnumber = 6 * 7\nflag = True\nif number > 40:\n    print(prefix, number, flag, str(False))\nelif number == 0:\n    print('zero')\nelse:\n    print('small')\nfor i in range(3):\n    print(i)\nprint(i)\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / generated.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated.content, encoding="utf-8")
            lint = subprocess.run([ruby, "-c", str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(lint.returncode, 0, lint.stderr + lint.stdout)
            run = subprocess.run([ruby, str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value= 42 True False\n0\n1\n2\n2\n")


if __name__ == "__main__":
    unittest.main()
