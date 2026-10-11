"""Tests for the deterministic Python-to-Kotlin adapter."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.python_kotlin_target import (
    PythonToKotlinTargetAdapter,
    UnsupportedPythonSyntax,
)


class PythonToKotlinTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            artifacts = PythonToKotlinTargetAdapter().generate(project, {})
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].relative_path, "Main.kt")
        return artifacts[0].content

    def test_generates_typed_kotlin_and_python_style_print(self):
        code = self._translate('x = 6\ny = x * 7\nprint("value", y, True)\n')
        self.assertIn("var x: Int = 6", code)
        self.assertIn("var y: Int = (x * 7)", code)
        self.assertIn('println(listOf<Any>("value", y, true).joinToString(" ") { pyString(it) })', code)
        self.assertIn('is Boolean -> if (value) "True" else "False"', code)

    def test_supports_print_only_if_elif_else_and_python_truthiness(self):
        code = self._translate(
            "x = 3\nlabel = 'ready'\n"
            "if x > 5:\n    print('high')\n"
            "elif x > 0 and label:\n    print('positive', x)\n"
            "else:\n    print('zero')\n"
        )
        self.assertIn("if ((x > 5)) {", code)
        self.assertIn("} else if (((x > 0) && (label.isNotEmpty()))) {", code)
        self.assertIn('println(listOf<Any>("positive", x).joinToString(" ") { pyString(it) })', code)

    def test_python_floor_division_and_modulo_semantics(self):
        code = self._translate("print(-3 // 2, -3 % 2)\n")
        self.assertIn("Math.floorDiv(-3, 2)", code)
        self.assertIn("Math.floorMod(-3, 2)", code)

    def test_rejects_unsupported_syntax_and_unsafe_types(self):
        cases = (
            ("x = 1\nx = 'text'\nprint(x)\n", "Changing the type of 'x'"),
            ("print([1, 2, 3])\n", "Unsupported expression syntax: List"),
            ("x = 2147483647 + 1\nprint(x)\n", "signed 32-bit Kotlin Int range"),
            ("x = 1\nif x:\n    x = 2\n", "conditional bodies may contain only print"),
            ("type = 1\nprint(type)\n", "not supported in Kotlin"),
            ("pyString = 1\nprint(pyString)\n", "not supported in Kotlin"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    @unittest.skipUnless(shutil.which("kotlinc") and shutil.which("java"), "Kotlin compiler and Java are required")
    def test_kotlin_runtime_matches_python_fixture(self):
        source = (
            "x = 3\nlabel = 'ready'\n"
            "if x > 5:\n    print('high')\n"
            "elif x > 0 and label:\n    print('positive', x)\n"
            "else:\n    print('zero')\n"
            "print(-3 // 2, -3 % 2)\n"
        )
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "Main.kt"
            jar_path = root / "program.jar"
            source_path.write_text(code, encoding="utf-8")
            compile_result = subprocess.run(
                [shutil.which("kotlinc"), str(source_path), "-include-runtime", "-d", str(jar_path)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            run = subprocess.run(
                [shutil.which("java"), "-jar", str(jar_path)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "positive 3\n-2 1\n")


if __name__ == "__main__":
    unittest.main()
