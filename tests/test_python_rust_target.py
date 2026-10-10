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
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "If"):
            self._translate("if True:\n    print('yes')\n")

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
