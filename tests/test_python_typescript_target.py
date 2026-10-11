"""Tests for the deterministic Python-to-TypeScript adapter."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.pipeline import SourceProject, SourceUnit
from polymigrate.migration.python_typescript_target import (
    PythonToTypeScriptTargetAdapter,
    UnsupportedPythonSyntax,
)


class PythonToTypeScriptTargetAdapterTests(unittest.TestCase):
    def _translate(self, source: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text(source, encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            artifacts = PythonToTypeScriptTargetAdapter().generate(project, {})
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0].relative_path, "main.ts")
        return artifacts[0].content

    def test_generates_typescript_extension_from_checked_subset(self):
        code = self._translate('x = 6\ny = x * 7\nprint(y)\n')
        self.assertIn("let x = 6;", code)
        self.assertIn("let y = (x * 7);", code)
        self.assertIn("console.log(y);", code)

    def test_rejects_typescript_reserved_identifiers_and_unsupported_syntax(self):
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "reserved by TypeScript"):
            self._translate("type = 1\nprint(type)\n")
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "Unsupported expression syntax"):
            self._translate("print([1, 2, 3])\n")

    def test_rejects_multiple_source_files(self):
        project = SourceProject(
            Path("."),
            "python",
            (
                SourceUnit("one.py", "print(1)\n", "unused"),
                SourceUnit("two.py", "print(2)\n", "unused"),
            ),
        )
        with self.assertRaisesRegex(UnsupportedPythonSyntax, "exactly one Python source file"):
            PythonToTypeScriptTargetAdapter().generate(project, {})

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node"), "TypeScript compiler and Node.js are required")
    def test_strict_typecheck_and_runtime_match_python_fixture(self):
        source = (
            "x = 2\n"
            "if x > 1:\n    print('go', x)\n"
            "for i in range(3):\n    print(i)\n"
        )
        code = self._translate(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.ts").write_text(code, encoding="utf-8")
            output = root / "compiled"
            compile_result = subprocess.run(
                [
                    shutil.which("tsc"), "--strict", "--target", "ES2020",
                    "--module", "commonjs", "--outDir", str(output), str(root / "main.ts"),
                ],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            run = subprocess.run(
                [shutil.which("node"), str(output / "main.js")],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout, "go 2\n0\n1\n2\n")


if __name__ == "__main__":
    unittest.main()
