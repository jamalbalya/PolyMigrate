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

    def test_rejects_unsupported_control_flow_instead_of_guessing(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Unsupported statement syntax: If"):
            PythonToRubyTargetAdapter().generate(
                project_for("value = 1\nif value:\n    print(value)\n"), {}
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

    def test_generated_ruby_runs_when_ruby_is_installed(self):
        ruby = shutil.which("ruby")
        if ruby is None:
            self.skipTest("Ruby CLI is not installed in this test environment")
        generated = PythonToRubyTargetAdapter().generate(
            project_for("prefix = 'value='\nnumber = 6 * 7\nflag = True\nprint(prefix, number, flag, str(False))\n"), {}
        )[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / generated.relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(generated.content, encoding="utf-8")
            lint = subprocess.run([ruby, "-c", str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(lint.returncode, 0, lint.stderr + lint.stdout)
            run = subprocess.run([ruby, str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value= 42 True False\n")


if __name__ == "__main__":
    unittest.main()
