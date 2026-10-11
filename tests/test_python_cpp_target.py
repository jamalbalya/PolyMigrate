"""Tests for the constrained deterministic Python-to-C++ translator."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.pipeline import SourceProject, SourceUnit
from polymigrate.migration.python_cpp_target import PythonToCppTargetAdapter, UnsupportedPythonSyntax


def project_for(source: str, path: str = "main.py") -> SourceProject:
    return SourceProject(
        Path("."),
        "python",
        (SourceUnit(path, source, hashlib.sha256(source.encode("utf-8")).hexdigest()),),
    )


class PythonToCppTranslatorTests(unittest.TestCase):
    def test_translates_assignments_arithmetic_and_positional_print(self):
        generated = PythonToCppTargetAdapter().generate(
            project_for("x = 6\ny = x * 7\nprint(y)\n"), {}
        )[0]
        self.assertEqual(generated.relative_path, "main.cpp")
        self.assertIn("std::int32_t x = 6;", generated.content)
        self.assertIn("std::int32_t y = (x * 7);", generated.content)
        self.assertIn("std::cout << polymigrate_string(y);", generated.content)
        self.assertIn("int main()", generated.content)

    def test_preserves_python_boolean_text_and_string_concatenation(self):
        generated = PythonToCppTargetAdapter().generate(
            project_for("prefix = 'hello ' + 'world'\nflag = True\nprint(prefix, flag, str(False))\n"), {}
        )[0].content
        self.assertIn('std::string prefix = (std::string("hello ") + std::string("world"));', generated)
        self.assertIn("bool flag = true;", generated)
        self.assertIn("polymigrate_string(false)", generated)
        self.assertIn('value ? "True" : "False"', generated)

    def test_translates_nested_source_paths_without_flattening_them(self):
        generated = PythonToCppTargetAdapter().generate(
            project_for("print('module')\n", "src/module.py"), {}
        )[0]
        self.assertEqual(generated.relative_path, "src/module.cpp")

    def test_rejects_branch_assignments_and_chained_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "bodies may contain only print"):
            PythonToCppTargetAdapter().generate(
                project_for("value = 1\nif value:\n    value = 2\nprint(value)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Chained comparisons"):
            PythonToCppTargetAdapter().generate(
                project_for("value = 1\nif 0 < value < 2:\n    print(value)\n"), {}
            )

    def test_rejects_reserved_and_implementation_reserved_identifiers(self):
        for name in ("class", "std", "__hidden", "_Hidden", "NULL", "INT32_MAX"):
            with self.subTest(name=name), self.assertRaises(UnsupportedPythonSyntax):
                PythonToCppTargetAdapter().generate(
                    project_for(f"{name} = 1" + chr(10) + f"print({name})" + chr(10)), {}
                )

    def test_rejects_signed_32_bit_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed 32-bit range"):
            PythonToCppTargetAdapter().generate(
                project_for("value = 2147483647 + 1\nprint(value)\n"), {}
            )

    def test_requires_single_source_file_for_standalone_program(self):
        source = project_for("print('one')\n")
        second = SourceUnit("other.py", "print('two')\n", hashlib.sha256(b"print('two')\n").hexdigest())
        project = SourceProject(Path("."), "python", (source.units[0], second))
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one Python source file"):
            PythonToCppTargetAdapter().generate(project, {})

    def test_translates_conditionals_and_python_string_truthiness(self):
        generated = PythonToCppTargetAdapter().generate(
            project_for("text = '0'\nif text:\n    print('truthy')\nelse:\n    print('falsey')\n"), {}
        )[0].content
        self.assertIn("if ((text != std::string(\"\")))", generated)
        self.assertIn("} else {", generated)

    def test_rejects_zero_step_and_excessive_range(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "step cannot be zero"):
            PythonToCppTargetAdapter().generate(
                project_for("for i in range(1, 5, 0):\n    print(i)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000 actual iterations"):
            PythonToCppTargetAdapter().generate(
                project_for("for i in range(10001):\n    print(i)\n"), {}
            )

    def test_rejects_range_counter_overflow_and_boolean_bounds(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "counter could overflow"):
            PythonToCppTargetAdapter().generate(
                project_for("for i in range(2147483646, 2147483647, 2):\n    print(i)\n"), {}
            )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "arguments must be integers"):
            PythonToCppTargetAdapter().generate(
                project_for("for i in range(True):\n    print(i)\n"), {}
            )

    def test_negative_step_range_loop_compiles_and_runs(self):
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is not installed in this test environment")
        generated = PythonToCppTargetAdapter().generate(
            project_for("for i in range(3, 0, -1):\n    print(i)\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / generated.relative_path
            path.write_text(generated.content, encoding="utf-8")
            executable = root / "program"
            build = subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(executable)],
                                   capture_output=True, text=True, timeout=20)
            self.assertEqual(build.returncode, 0, build.stderr + build.stdout)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "3\n2\n1\n")

    def test_zero_iteration_range_does_not_define_loop_variable(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "used before assignment"):
            PythonToCppTargetAdapter().generate(
                project_for("for i in range(0):\n    print(i)\nprint(i)\n"), {}
            )

    def test_generated_cpp_compiles_and_runs_when_gpp_is_installed(self):
        compiler = shutil.which("g++")
        if compiler is None:
            self.skipTest("g++ is not installed in this test environment")
        generated = PythonToCppTargetAdapter().generate(
            project_for("prefix = 'value='\nnumber = 6 * 7\nflag = True\nif number > 40:\n    print(prefix, number, flag, str(False))\nelif number == 0:\n    print('zero')\nelse:\n    print('small')\nfor i in range(3):\n    print(i)\nprint(i)\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / generated.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated.content, encoding="utf-8")
            executable = root / "program"
            compile_result = subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(executable)],
                capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr + compile_result.stdout)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value= 42 True False\n0\n1\n2\n2\n")


if __name__ == "__main__":
    unittest.main()
