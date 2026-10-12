"""Tests for the deterministic Python-to-Swift subset."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.python_swift_target import PythonToSwiftTargetAdapter, UnsupportedPythonSyntax


class PythonToSwiftTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            artifacts = PythonToSwiftTargetAdapter().generate(project, {})
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].relative_path, "main.swift")
        return artifacts[0].content

    def test_generates_typed_swift_and_python_style_print(self):
        code = self._translate('count = 6\nlabel = "value"\nactive = True\nprint(label, count, active)\n')
        self.assertIn("let count: Int32 = 6", code)
        self.assertIn('let label: String = "value"', code)
        self.assertIn("let active: Bool = true", code)
        self.assertIn('print((active ? "True" : "False"), terminator: "")', code)

    def test_generates_print_only_conditionals_and_rejects_unsafe_branches(self):
        code = self._translate(
            "score = 3\n"
            "if score > 5:\n    print('high')\n"
            "elif score > 0 and score < 5:\n    print('positive', score)\n"
            "else:\n    print('other')\n"
            "label = 'ready'\nif label == 'ready':\n    print('match')\nelse:\n    print('miss')\n"
            "empty = ''\nif empty:\n    print('nonempty')\nelse:\n    print('empty')\n"
        )
        self.assertIn("if (score > 5) {", code)
        self.assertIn("} else if ((score > 0) && (score < 5)) {", code)
        self.assertIn('unicodeScalars.elementsEqual(("ready").unicodeScalars)', code)
        self.assertIn("!(empty).isEmpty", code)

        cases = (
            ("x = 1\nif x:\n    if x:\n        print(x)\n", "conditional bodies may contain only print"),
            ("x = 1\nif 0 < x < 3:\n    print(x)\n", "Chained comparisons"),
            ("label = 'x'\nif label < 'z':\n    print(label)\n", "String ordering comparisons"),
            ("flag = True\nif flag < False:\n    print(flag)\n", "Boolean ordering comparisons"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_conditional_assignments_preserve_types_and_merge_static_facts(self):
        code = self._translate(
            "score = 3\nvalue = 0\n"
            "if score > 5:\n    value = 10\n"
            "elif score > 0:\n    value = score + 2\n"
            "else:\n    value = -1\n"
            "print(value)\n"
            "x = 1\nif score > 0:\n    x = 2\nelse:\n    x = 2\n"
            "print(x + 1)\n"
            "label = 'before'\nif score > 0:\n    label = 'same'\nelse:\n    label = 'same'\n"
            "length = len(label)\nprint(length)\n"
        )
        self.assertIn("var value: Int32 = 0", code)
        self.assertIn("var x: Int32 = 1", code)
        self.assertIn('var label: String = "before"', code)
        self.assertIn("x = 2", code)
        self.assertIn("let length: Int32 = Int32((label).unicodeScalars.count)", code)

        cases = (
            ("if True:\n    x = 1\n", "conditional assignments must target existing variables"),
            ("x = 1\nif x:\n    x = 'text'\n", "must preserve the variable type"),
            ("x = 1\nif x:\n    x = 2\nprint(x + 1)\n", "cannot be proven safe"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_range_loops_can_update_existing_variables_safely(self):
        code = self._translate(
            "counter = 0\nfor i in range(3):\n    counter = counter + 1\nprint(counter)\n"
        )
        self.assertIn("var counter: Int32 = 0", code)
        self.assertIn("counter = (counter + 1)", code)

        cases = (
            ("x = 2147483646\nfor i in range(2):\n    x = x + 1\n", "signed Int32 range"),
            ("for i in range(3):\n    x = 1\n", "must target existing variables"),
            ("x = 1\nfor i in range(3):\n    x = 'text'\n", "must preserve the variable type"),
            ("for i in range(3):\n    i = i + 1\n", "cannot reassign the loop variable"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_generates_bounded_range_loops_and_rejects_unsafe_forms(self):
        code = self._translate(
            "start = 1\nstop = 5\n"
            "for i in range(start, stop, 2):\n    print(i)\n"
            "for j in range(3, -1, -2):\n    print(j)\n"
        )
        self.assertIn("for i in stride(from: Int32(start), to: Int32(stop), by: Int(2)) {", code)
        self.assertIn("for j in stride(from: Int32(3), to: Int32(-1), by: Int(-2)) {", code)

        cases = (
            ("for i in range(3):\n    print(i)\nprint(i)\n", "Use of a Swift range-loop variable after its loop"),
            ("for i in range(0, 3, 0):\n    print(i)\n", "step cannot be zero"),
            ("for i in range(10001):\n    print(i)\n", "limited to 10000 iterations"),
            ("i = 2\nfor i in range(3):\n    print(i)\n", "cannot shadow assigned variables"),
            ("for i in range(3):\n    i = i + 1\n", "loop bodies may contain only print"),
            ("for i in range(3):\n    if i:\n        print(i)\n", "loop bodies may contain only print"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_rejects_unsupported_syntax_type_changes_and_overflow(self):
        cases = (
            ("x = 1\nprint(x + 2147483647)\n", "signed Int32 range"),
            ('x = 1\nx = "text"\nprint(x)\n', "Changing the type"),
            ("print([1, 2])\n", "Unsupported expression syntax: List"),
            ("var = 2\nprint(var)\n", "not supported in Swift"),
            ("print(value)\n", "used before assignment"),
            ("def f():\n    print(1)\n", "Unsupported statement syntax: FunctionDef"),
            ('x = "bad\\x00value"\nprint(x)\n', "unsupported control characters"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    def test_rejects_shadowed_builtins_and_unsafe_abs(self):
        cases = (
            ("abs = 2\nprint(abs)\n", "not supported in Swift"),
            ("x = abs(-2147483648)\nprint(x)\n", "signed Int32 range"),
            ("print(str=True)\n", "no keywords"),
        )
        for source, message in cases:
            with self.subTest(source=source), self.assertRaisesRegex(UnsupportedPythonSyntax, message):
                self._translate(source)

    @unittest.skipUnless(os.environ.get("POLYMIGRATE_RUN_SWIFT_E2E") == "1" and shutil.which("swiftc"), "Run in the dedicated Swift CI job")
    def test_compiled_swift_matches_python_output(self):
        source = (
            'count = 6\nlabel = "value"\nactive = True\n'
            "print(label, count, active)\nprint(-3 * 2, abs(-7))\nprint()\n"
            "print(str(False))\nprint(len('😀'))\n"
            "score = 3\nif score > 5:\n    print('high')\n"
            "elif score > 0 and score < 5:\n    print('positive', score)\n"
            "else:\n    print('other')\n"
            "label2 = 'ready'\nif label2 == 'ready':\n    print('match')\nelse:\n    print('miss')\n"
            "unicode_a = 'é'\nunicode_b = 'e\\u0301'\n"
            "if unicode_a == unicode_b:\n    print('unicode-equal')\nelse:\n    print('unicode-different')\n"
            "empty = ''\nif empty:\n    print('nonempty')\nelse:\n    print('empty')\n"
            "active = True\nif active == True:\n    print('enabled')\nelse:\n    print('disabled')\n"
            "for i in range(3):\n    print(i + 1)\n"
            "for j in range(3, -1, -2):\n    print(j)\n"
            "value = 0\nif score > 5:\n    value = 10\n"
            "elif score > 0:\n    value = score + 2\n"
            "else:\n    value = -1\nprint(value)\n"
            "x = 1\nif score > 0:\n    x = 2\nelse:\n    x = 2\nprint(x + 1)\n"
            "label3 = 'before'\nif score > 0:\n    label3 = 'same'\nelse:\n    label3 = 'same'\n"
            "length = len(label3)\nprint(length)\n"
            "counter = 0\nfor k in range(3):\n    counter = counter + 1\nprint(counter)\n"
            "counter2 = 0\nfor j in range(3):\n    counter2 = counter2 + j\nprint(counter2)\n"
        )
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            swift_file = root / "main.swift"
            executable = root / "program"
            swift_file.write_text(code, encoding="utf-8")
            compiled = subprocess.run(
                [shutil.which("swiftc"), "-warnings-as-errors", str(swift_file), "-o", str(executable)],
                capture_output=True, text=True, timeout=90,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "value 6 True\n-6 7\n\nFalse\n1\npositive 3\nmatch\nunicode-different\nempty\nenabled\n1\n2\n3\n3\n1\n5\n3\n4\n3\n3\n")


if __name__ == "__main__":
    unittest.main()
