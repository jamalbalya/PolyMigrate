"""Tests for the deterministic Python-to-Rust adapter."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.python_rust_target import (
    PythonToRustTargetAdapter,
    UnsupportedPythonSyntax,
)


class PythonToRustTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            artifacts = PythonToRustTargetAdapter().generate(project, {})
        return {item.relative_path: item.content for item in artifacts}

    def test_emits_minimal_cargo_project(self):
        files = self._translate('x = 6\ny = x * 7\nprint(y)\n')
        self.assertIn('[package]', files["Cargo.toml"])
        self.assertIn("let mut x = 6;", files["src/main.rs"])
        self.assertIn("println!(\"{}\", y);", files["src/main.rs"])

    def test_string_literal_print(self):
        files = self._translate('print("hello")\n')
        self.assertIn('println!(\"{}\", "hello");', files["src/main.rs"])

    def test_accepts_signed_i32_minimum(self):
        files = self._translate("x = -2147483648\nprint(x)\n")
        self.assertIn("let mut x = -2147483648;", files["src/main.rs"])

    def test_unicode_string_literals_remain_valid_rust_source(self):
        files = self._translate('print("café")\n')
        self.assertIn('"café"', files["src/main.rs"])

    def test_escapes_rust_control_characters(self):
        files = self._translate('print("a\\b\\f")\n')
        self.assertIn('\\u{8}', files["src/main.rs"])
        self.assertIn('\\u{c}', files["src/main.rs"])

    def test_rejects_lone_unicode_surrogates(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Lone Unicode surrogates"):
            self._translate('print("\\ud800")\n')

    def test_if_else_comparison_is_translated(self):
        files = self._translate(
            'x = 6\nif x > 0:\n    print("positive")\nelse:\n    print("non-positive")\n'
        )
        self.assertIn("if (x > 0) {", files["src/main.rs"])
        self.assertIn("} else {", files["src/main.rs"])
        self.assertIn('println!("{}", "positive");', files["src/main.rs"])

    def test_compound_conditions_and_truthiness_are_translated(self):
        files = self._translate('x = 6\nif x and x < 10:\n    print("in range")\n')
        self.assertIn("&&", files["src/main.rs"])
        self.assertIn("(x != 0)", files["src/main.rs"])

    def test_rejects_conditional_chains_over_twenty_branches(self):
        lines = ["x = 0", "if x == 0:", "    print('match')"]
        for value in range(1, 21):
            lines.extend([f"elif x == {value}:", "    print('match')"])
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "20 branches"):
            self._translate("\n".join(lines) + "\n")

    def test_rejects_chained_comparisons(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Chained comparisons"):
            self._translate('x = 6\nif 0 < x < 10:\n    print("in range")\n')

    def test_rejects_assignment_inside_conditional(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "only print"):
            self._translate("x = 1\nif x > 0:\n    y = 2\nprint(x)\n")

    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain is required")
    def test_if_else_generated_project_builds_and_runs(self):
        files = self._translate(
            'x = 6\nif x > 0:\n    print("positive")\nelse:\n    print("non-positive")\n'
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            run = subprocess.run(
                ["cargo", "run", "--offline", "--quiet"], cwd=root,
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "positive\n")

    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain is required")
    def test_elif_chain_generated_project_matches_python_output(self):
        source = 'x = 2\nif x == 1:\n    print("one")\nelif x == 2:\n    print("two")\nelse:\n    print("other")\n'
        files = self._translate(source)
        self.assertIn("else if", files["src/main.rs"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            run = subprocess.run(
                ["cargo", "run", "--offline", "--quiet"], cwd=root,
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "two\n")

    def test_range_loop_is_translated(self):
        files = self._translate("for i in range(3):\n    print(i)\n")
        self.assertIn("for i in 0..3 {", files["src/main.rs"])
        self.assertIn('println!("{}", i);', files["src/main.rs"])

    def test_range_loop_uses_statically_known_bounds(self):
        files = self._translate("start = 1\nstop = 4\nfor i in range(start, stop):\n    print(i)\n")
        self.assertIn("for i in start..stop {", files["src/main.rs"])

    def test_range_steps_are_bounded_and_zero_is_rejected(self):
        code = self._translate("for i in range(0, 5, 2):\n    print(i)\n")
        negative_code = self._translate("for i in range(5, 0, -2):\n    print(i)\n")
        self.assertIn("i += 2;", code)
        self.assertIn("while i > 0", negative_code)
        self._translate("for i in range(0, 10001, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "step cannot be zero"):
            self._translate("for i in range(0, 5, 0):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "overflow the target integer range"):
            self._translate("for i in range(2147483646, 2147483647, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000-iteration"):
            self._translate("for i in range(0, 20002, 2):\n    print(i)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "10000-iteration"):
            self._translate("for i in range(10001):\n    print(i)\n")

    def test_rejects_loop_variable_shadowing(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "cannot shadow"):
            self._translate("i = 1\nfor i in range(3):\n    print(i)\n")

    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain is required")
    def test_signed_range_steps_generated_project_builds_and_runs(self):
        source = "for i in range(0, 5, 2):\n    print(i)\nfor j in range(5, 0, -2):\n    print(j)\n"
        files = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            run = subprocess.run(
                ["cargo", "run", "--offline", "--quiet"], cwd=root,
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "0\n2\n4\n5\n3\n1\n")

    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain is required")
    def test_range_loop_generated_project_builds_and_runs(self):
        files = self._translate("for i in range(3):\n    print(i)\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            run = subprocess.run(
                ["cargo", "run", "--offline", "--quiet"], cwd=root,
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "0\n1\n2\n")

    def test_rejects_integer_overflow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "signed Rust i32 range"):
            self._translate("x = 2147483647\ny = x + 1\nprint(y)\n")

    def test_rejects_string_concatenation(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Only integer arithmetic"):
            self._translate('print("hello" + " world")\n')

    def test_rejects_underscore_placeholder(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "underscore placeholder"):
            self._translate("_ = 1\nprint(_)\n")

    def test_rejects_unsupported_control_flow(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "While"):
            self._translate("while True:\n    print('yes')\n")

    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain is required")
    def test_generated_project_builds_and_runs_offline(self):
        files = self._translate("x = 6\ny = x * 7\nprint(y)\n")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            run = subprocess.run(
                ["cargo", "run", "--offline", "--quiet"], cwd=root,
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "42\n")


if __name__ == "__main__":
    unittest.main()
