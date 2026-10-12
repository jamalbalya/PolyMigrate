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
            "active = True\nif active == True:\n    print('enabled')\nelse:\n    print('disabled')\n"
            "value = 0\nif score > 5:\n    value = 10\nelif score > 0:\n    value = score + 2\nelse:\n    value = -1\nprint(value)\n"
            "label2 = 'ready'\nif label2 == 'ready':\n    label2 = 'go'\nelse:\n    label2 = 'stop'\nprint(label2)\n"
            "counter = 0\nif active:\n    counter += 1\nelse:\n    counter += 2\nprint(counter)\n"
        )
        self.assertIn("} else if", code)
        self.assertIn("strcmp(label, \"ready\") == 0", code)
        self.assertIn("(empty)[0] != 0", code)

    def test_c_conditionals_reject_assignments_chained_comparisons_and_string_ordering(self):
        cases = (
            ("x = 1\nif x:\n    y = 2\n", "conditional assignments must target existing variables"),
            ("x = 1\nif x:\n    x = 'bad'\n", "preserve the variable type"),
            ("x = 1\nif x:\n    x = x + 1\nprint(x + 1)\n", "cannot be proven safe"),
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
            "active = True\nif active == True:\n    print('enabled')\nelse:\n    print('disabled')\n"
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
            self.assertEqual(run.stdout, "positive 3\nmatch\nempty\nenabled\n5\ngo\n1\n")

    def test_bounded_while_loop_generation_and_fail_closed_cases(self):
        code = self._translate(
            "count = 3\nwhile count > 0:\n    count -= 1\n    print(count)\nprint(count)\n"
        )
        self.assertIn("while ((count > 0))", code)
        self.assertIn("count -= 1;", code)
        cases = (
            ("count = 1\nwhile count > 0:\n    print(count)\n", "does not update its condition variables"),
            ("count = 1\nwhile count > 0:\n    count = count\n", "made no progress"),
            ("count = 2147483647\nwhile count > 0:\n    count += 1\n", "signed 32-bit C range"),
            ("while True:\n    print(1)\n", "one integer comparison"),
            ("count = 1\nwhile count > 0:\n    other = count - 1\n", "existing integer variables"),
            ("count = 1\nwhile count > 0:\n    count = 'bad'\n", "must remain integer-valued"),
            ("count = 1\nwhile count > 0:\n    count -= 1\nelse:\n    print(count)\n", "while/else"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    @unittest.skipUnless(shutil.which("gcc"), "GCC is required for C runtime equivalence")
    def test_compiled_c_while_loop_matches_python_fixture(self):
        source = (
            "count = 3\nwhile count > 0:\n    count -= 1\n    print(count)\n"
            "print(count)\n"
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
            self.assertEqual(run.stdout, "2\n1\n0\n0\n")

    def test_range_loop_integer_updates_preserve_static_facts_and_reject_unsafe_cases(self):
        code = self._translate(
            "total = 0\nfor i in range(4):\n    total += i\nprint(total)\n"
        )
        self.assertIn("total += i;", code)
        cases = (
            ("for i in range(2):\n    total = i\n", "existing integer variables"),
            ("total = 0\nfor i in range(2):\n    i += 1\n", "loop index reassignment"),
            ("total = 0\nfor i in range(2):\n    total = 'bad'\n", "remain integer-valued"),
            ("total = 2147483640\nfor i in range(10):\n    total += 1\n", "signed 32-bit C range"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_zero_iteration_range_loop_preserves_variable_values(self):
        code = self._translate(
            "total = 1\nfor i in range(0):\n    total = total + 1\nprint(total)\n"
        )
        self.assertNotIn("while (i", code)
        self.assertIn('printf("%" PRId32, (int32_t)(total));', code)

    def test_bounded_range_loop_generation_and_fail_closed_cases(self):
        code = self._translate("for i in range(5, 0, -2):\n    print(i)\n")
        self.assertIn("int32_t i = 5;", code)
        self.assertIn("while (i > 0)", code)
        self.assertIn("i += -2;", code)
        self.assertIn("i = 1;", code)
        cases = (
            ("for i in range(2):\n    i = 1\n", "loop index reassignment"),
            ("for i in range(2):\n    print(i)\nelse:\n    print(0)\n", "for/else"),
            ("for i in range(3, 1, 0):\n    print(i)\n", "step cannot be zero"),
            ("for i in range(10001):\n    print(i)\n", "limited to 10000"),
            ("for i in range(0):\n    print(i)\nprint(i)\n", "used before assignment"),
            ("range = 3\nfor i in range(2):\n    print(i)\n", "conflicts with a supported C builtin"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    @unittest.skipUnless(shutil.which("gcc"), "GCC is required for C runtime equivalence")
    def test_compiled_c_range_loops_match_python_fixture(self):
        source = (
            "for i in range(3):\n    print(i)\n"
            "print(i)\n"
            "for j in range(5, 0, -2):\n    print(j)\n"
            "total = 0\nfor k in range(4):\n    total += k\nprint(total)\n"
            "sum_result = 0\nfor q in range(4):\n    sum_result = sum_result + q\nprint(sum_result)\n"
            "product = 1\nfor n in range(1, 5):\n    product *= n\nprint(product)\n"
            "unchanged = 1\nfor z in range(0):\n    unchanged = unchanged + 1\nprint(unchanged)\n"
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
            self.assertEqual(run.stdout, "0\n1\n2\n2\n5\n3\n1\n6\n6\n24\n1\n")

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
