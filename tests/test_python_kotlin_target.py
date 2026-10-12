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

    def test_escapes_kotlin_string_templates(self):
        code = self._translate("print('$value')\n")
        self.assertIn(r'"\$value"', code)

    def test_python_floor_division_and_modulo_semantics(self):
        code = self._translate("print(-3 // 2, -3 % 2)\n")
        self.assertIn("Math.floorDiv(-3, 2)", code)
        self.assertIn("Math.floorMod(-3, 2)", code)

    def test_rejects_unsupported_syntax_and_unsafe_types(self):
        cases = (
            ("x = 1\nx = 'text'\nprint(x)\n", "Changing the type of 'x'"),
            ("print([1, 2, 3])\n", "Unsupported expression syntax: List"),
            ("x = 2147483647 + 1\nprint(x)\n", "signed 32-bit Kotlin Int range"),
            ("x = 1\nif x:\n    y = 2\n", "previously assigned variables"),
            ("when = 1\nprint(when)\n", "not supported in Kotlin"),
            ("pyString = 1\nprint(pyString)\n", "not supported in Kotlin"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_len_uses_unicode_code_point_semantics(self):
        code = self._translate("text = 'A😀é'\nsize = len(text)\nprint(size)\n")
        self.assertIn("text.codePointCount(0, text.length)", code)
        self.assertIn("var size: Int = text.codePointCount(0, text.length)", code)

    def test_len_rejects_non_string_arguments_and_builtin_shadowing(self):
        cases = (
            ("print(len(3))\n", "len\\(\\) supports string values only"),
            ("len = 1\nprint(len('x'))\n", "Shadowing the len\\(\\) builtin is not supported"),
            ("print(len('a', 'b'))\n", "supports exactly one positional argument"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_augmented_assignments_support_bounded_int_and_string_operators(self):
        code = self._translate(
            "x = 1\nx += 2\nx *= 2\ns = 'a'\ns += 'b'\nprint(x, s)\n"
        )
        self.assertIn("x += 2", code)
        self.assertIn("x *= 2", code)
        self.assertIn('s += "b"', code)
        cases = (
            ("x = 1\nx /= 2\n", "Only Int"),
            ("s = 'a'\ns -= 'b'\n", "Only Int"),
            ("x += 1\n", "previously assigned variables"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_conditional_assignments_merge_static_facts(self):
        code = self._translate(
            "x = 1\nif x > 0:\n    x = 2\nelse:\n    x = 2\nprint(x + 1)\n"
        )
        self.assertIn("if ((x > 0))", code)
        self.assertIn("x = 2", code)
        self.assertIn("var x: Int = 1", code)

    def test_conditional_assignments_preserve_runtime_branch_values(self):
        code = self._translate(
            "x = 1\nif x > 0:\n    x = 2\nelse:\n    x = 3\nprint(x)\n"
        )
        self.assertIn("} else {", code)
        self.assertIn("x = 3", code)

    def test_conditional_assignments_reject_new_variables_type_changes_and_nested_control(self):
        cases = (
            ("x = 1\nif x > 0:\n    y = 2\n", "previously assigned variables"),
            ("x = 1\nif x > 0:\n    x = 'wrong'\n", "cannot change a variable's type"),
            ("x = 1\nif x > 0:\n    if x > 1:\n        print(x)\n", "Conditional bodies may contain only print"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_bounded_while_loop_updates_integer_state_and_matches_python(self):
        code = self._translate("n = 3\nwhile n > 0:\n    n = n - 1\n    print(n)\nprint(n)\n")
        self.assertIn("while ((n > 0))", code)
        self.assertIn("n = (n - 1)", code)

    def test_while_loops_fail_closed_without_proven_termination(self):
        cases = (
            ("n = 1\nwhile n > 0:\n    print(n)\n", "does not update its condition variables"),
            ("n = 1\nwhile n > 0:\n    n = n\n", "made no progress"),
            ("n = 0\nwhile n < 10001:\n    n = n + 1\n", "could not be proven to terminate within 10000 iterations"),
            ("text = 'x'\nwhile text:\n    print(text)\n", "while conditions must be one simple integer comparison"),
            ("n = 1\nwhile n > 0:\n    if n:\n        print(n)\n", "while bodies may contain only print"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_bounded_range_loops_preserve_positive_and_negative_steps(self):
        code = self._translate(
            "for i in range(0, 5, 2):\n    print(i)\n"
            "for j in range(5, 0, -2):\n    print(j)\n"
        )
        self.assertIn("for (i in 0..4 step 2)", code)
        self.assertIn("for (j in 5 downTo 1 step 2)", code)

    def test_range_loop_preserves_last_value_when_referenced_after(self):
        code = self._translate("for i in range(3):\n    print(i)\nprint(i)\n")
        self.assertIn("for (i in 0..2 step 1)", code)
        self.assertIn("var i: Int = 2", code)

    def test_range_loops_fail_closed_on_zero_step_large_ranges_and_undefined_loop_value(self):
        cases = (
            ("for i in range(0, 5, 0):\n    print(i)\n", "step cannot be zero"),
            ("for i in range(10001):\n    print(i)\n", "limited to 10000"),
            ("for i in range(0):\n    print(i)\nprint(i)\n", "loop variable undefined"),
            ("for i in range(3):\n    i = 4\n", "loop bodies may contain only print"),
            ("range = 3\nfor i in range(3):\n    print(i)\n", "Shadowing the range\\(\\) builtin is not supported"),
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
            "print('$value')\n"
            "text = 'A😀é'\nprint(len(text))\nprint(len('😀'))\n"
            "for i in range(0, 5, 2):\n    print(i)\n"
            "for j in range(5, 0, -2):\n    print(j)\n"
            "for k in range(3):\n    print(k)\n"
            "print(k)\n"
            "score = 1\nif score > 0:\n    score = 2\nelse:\n    score = 3\nprint(score)\n"
            "word = 'a'\nif score > 0:\n    word += 'b'\nelse:\n    word += 'b'\nprint(word)\n"
            "x = 1\nif x > 0:\n    x += 1\nelse:\n    x += 1\nprint(x + 1)\n"
            "count = 3\nwhile count > 0:\n    count -= 1\n    print(count)\nprint(count)\n"
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
            self.assertEqual(run.stdout, "positive 3\n-2 1\n$value\n3\n1\n0\n2\n4\n5\n3\n1\n0\n1\n2\n2\n2\nab\n3\n2\n1\n0\n0\n")


if __name__ == "__main__":
    unittest.main()
