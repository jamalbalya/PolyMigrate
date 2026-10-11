"""Tests for the constrained deterministic Python-to-PHP translator."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.pipeline import SourceProject, SourceUnit
from polymigrate.migration.python_php_target import PythonToPHPTargetAdapter, UnsupportedPythonSyntax


def project_for(source: str, path: str = "main.py") -> SourceProject:
    return SourceProject(
        Path("."),
        "python",
        (SourceUnit(path, source, hashlib.sha256(source.encode("utf-8")).hexdigest()),),
    )


class PythonToPHPTranslatorTests(unittest.TestCase):
    def test_translates_assignments_arithmetic_and_positional_print(self):
        artifacts = PythonToPHPTargetAdapter().generate(
            project_for("x = 6\ny = x * 7\nprint(y)\n"), {}
        )
        self.assertEqual([item.relative_path for item in artifacts], ["main.php"])
        generated = artifacts[0].content
        self.assertTrue(generated.startswith("<?php\n"))
        self.assertIn("$x = 6;", generated)
        self.assertIn("$y = ($x * 7);", generated)
        self.assertIn("echo implode(' ', array_map('polymigrateString', [$y])) . PHP_EOL;", generated)
        self.assertIn("function polymigrateString($value): string", generated)

    def test_preserves_python_boolean_text_and_string_concatenation(self):
        generated = PythonToPHPTargetAdapter().generate(
            project_for("prefix = 'hello ' + 'world'\nflag = True\nprint(prefix, flag, str(False))\n"), {}
        )[0].content
        self.assertIn("$prefix = ('hello ' . 'world');", generated)
        self.assertIn("$flag = true;", generated)
        self.assertIn("array_map('polymigrateString', [$prefix, $flag, polymigrateString(false)])", generated)
        self.assertIn("polymigrateString(false)", generated)
        self.assertIn("return $value ? 'True' : 'False';", generated)

    def test_translates_nested_source_paths_without_flattening_them(self):
        artifacts = PythonToPHPTargetAdapter().generate(
            project_for("print('module')\n", "src/module.py"), {}
        )
        self.assertEqual(artifacts[0].relative_path, "src/module.php")

    def test_rejects_assignments_inside_branches_instead_of_guessing(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "bodies may contain only print"):
            PythonToPHPTargetAdapter().generate(
                project_for("value = 1\nif value:\n    value = 2\nprint(value)\n"), {}
            )

    def test_rejects_chained_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Chained comparisons"):
            PythonToPHPTargetAdapter().generate(
                project_for("value = 1\nif 0 < value < 2:\n    print(value)\n"), {}
            )

    def test_translates_bounded_range_loop_and_preserves_python_loop_value(self):
        php = shutil.which("php")
        if php is None:
            self.skipTest("PHP CLI is not installed in this test environment")
        generated = PythonToPHPTargetAdapter().generate(
            project_for("for i in range(3):\n    print(i)\nprint(i)\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / generated.relative_path
            path.write_text(generated.content, encoding="utf-8")
            lint = subprocess.run([php, "-l", str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(lint.returncode, 0, lint.stderr + lint.stdout)
            run = subprocess.run([php, str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "0\n1\n2\n2\n")

    def test_translates_negative_step_range_loop(self):
        php = shutil.which("php")
        if php is None:
            self.skipTest("PHP CLI is not installed in this test environment")
        generated = PythonToPHPTargetAdapter().generate(
            project_for("for i in range(3, 0, -1):\n    print(i)\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / generated.relative_path
            path.write_text(generated.content, encoding="utf-8")
            run = subprocess.run([php, str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "3\n2\n1\n")

    def test_rejects_php_reserved_variables(self):
        for name in ("this", "GLOBALS", "_SERVER"):
            with self.subTest(name=name), self.assertRaisesRegex(UnsupportedPythonSyntax, "reserved by PHP"):
                PythonToPHPTargetAdapter().generate(
                    project_for(f"{name} = 1" + chr(10) + f"print({name})" + chr(10), {})
                )

    def test_rejects_zero_step_and_excessive_range(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "step cannot be zero"):
            PythonToPHPTargetAdapter().generate(
                project_for("for i in range(1, 5, 0):\n    print(i)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000 actual iterations"):
            PythonToPHPTargetAdapter().generate(
                project_for("for i in range(10001):\n    print(i)\n"), {}
            )

    def test_rejects_range_counter_overflow_and_boolean_bounds(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "counter could overflow"):
            PythonToPHPTargetAdapter().generate(
                project_for("for i in range(2147483646, 2147483647, 2):\n    print(i)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "arguments must be integers"):
            PythonToPHPTargetAdapter().generate(
                project_for("for i in range(True):\n    print(i)\n"), {}
            )

    def test_zero_iteration_loop_does_not_define_loop_variable(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "used before assignment"):
            PythonToPHPTargetAdapter().generate(
                project_for("for i in range(0):\n    print(i)\nprint(i)\n"), {}
            )

    def test_rejects_signed_32_bit_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed 32-bit range"):
            PythonToPHPTargetAdapter().generate(
                project_for("value = 2147483647 + 1\nprint(value)\n"), {}
            )

    def test_generated_php_runs_when_php_is_installed(self):
        php = shutil.which("php")
        if php is None:
            self.skipTest("PHP CLI is not installed in this test environment")
        generated = PythonToPHPTargetAdapter().generate(
            project_for("prefix = 'value='\nnumber = 6 * 7\nif number > 40:\n    print(prefix, number, True)\nelif number == 0:\n    print('zero')\nelse:\n    print('small')\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / generated.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated.content, encoding="utf-8")
            lint = subprocess.run([php, "-l", str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(lint.returncode, 0, lint.stderr + lint.stdout)
            run = subprocess.run([php, str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value= 42 True\n")


if __name__ == "__main__":
    unittest.main()
