"""Tests for the constrained deterministic Python-to-C adapter."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.python_c_target import PythonToCTargetAdapter, UnsupportedPythonSyntax


class PythonToCTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            artifacts = PythonToCTargetAdapter().generate(project, {})
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].relative_path, "main.c")
        return artifacts[0].content

    def test_generates_typed_c11_and_python_style_print(self):
        code = self._translate('count = 6\nlabel = "value"\nactive = True\nprint(label, count, active)\n')
        self.assertIn("int32_t count = 6;", code)
        self.assertIn('const char * label = "value";', code)
        self.assertIn("bool active = true;", code)
        self.assertIn('printf("%" PRId32, (int32_t)(count));', code)
        self.assertIn('printf("%s", (active) ? "True" : "False");', code)

    def test_rejects_unsupported_syntax_unsafe_values_and_type_changes(self):
        cases = (
            ("x = 1\nprint(x + 2147483647)\n", "signed 32-bit C range"),
            ("x = 1\nx = 'text'\nprint(x)\n", "Changing the type of 'x'"),
            ("print([1, 2])\n", "Unsupported expression syntax: List"),
            ("int = 2\nprint(int)\n", "not a supported C identifier"),
            ("x = 'bad\\x00value'\nprint(x)\n", "unsupported control characters"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_print_only_if_elif_else_supports_scalar_truthiness_and_string_equality(self):
        code = self._translate(
            "score = 3\nlabel = 'ready'\nempty = ''\n"
            "if score > 5:\n    print('high')\n"
            "elif score > 0 and score < 5:\n    print('positive', score)\n"
            "else:\n    print('other')\n"
            "if label == 'ready':\n    print('match')\nelse:\n    print('miss')\n"
            "if empty:\n    print('nonempty')\nelse:\n    print('empty')\n"
        )
        self.assertIn("} else if", code)
        self.assertIn("strcmp(label, \"ready\") == 0", code)
        self.assertIn("(empty)[0] != 0", code)

    def test_c_conditionals_reject_assignments_chained_comparisons_and_string_ordering(self):
        cases = (
            ("x = 1\nif x:\n    x = 2\n", "conditional bodies may contain only print"),
            ("x = 1\nif 0 < x < 3:\n    print(x)\n", "Chained comparisons are not supported"),
            ("label = 'x'\nif label < 'z':\n    print(label)\n", "String ordering comparisons are not supported"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    @unittest.skipUnless(shutil.which("gcc"), "GCC is required for C runtime equivalence")
    def test_compiled_c_conditionals_match_python_fixture(self):
        source = (
            "score = 3\nlabel = 'ready'\nempty = ''\n"
            "if score > 5:\n    print('high')\n"
            "elif score > 0 and score < 5:\n    print('positive', score)\n"
            "else:\n    print('other')\n"
            "if label == 'ready':\n    print('match')\nelse:\n    print('miss')\n"
            "if empty:\n    print('nonempty')\nelse:\n    print('empty')\n"
        )
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "main.c"
            executable = root / "program"
            source_path.write_text(code, encoding="utf-8")
            compile_result = subprocess.run(
                [shutil.which("gcc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(source_path), "-o", str(executable)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "positive 3\nmatch\nempty\n")

    @unittest.skipUnless(shutil.which("gcc"), "GCC is required for C runtime equivalence")
    def test_compiled_c_output_matches_python_fixture(self):
        source = (
            'count = 3\nlabel = "ready"\nactive = True\n'
            'print(label, count, active)\nprint(-3 * 2, abs(-7))\nprint()\n'
        )
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "main.c"
            executable = root / "program"
            source_path.write_text(code, encoding="utf-8")
            compile_result = subprocess.run(
                [shutil.which("gcc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(source_path), "-o", str(executable)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "ready 3 True\n-6 7\n\n")


if __name__ == "__main__":
    unittest.main()
