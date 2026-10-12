"""End-to-end behavior-equivalence smoke tests for deterministic bidirectional pairs.

These tests execute both the original program and the generated artifact. They prove
only the tiny arithmetic fixture below, not general language-pair equivalence.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_python_target import GoToPythonTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine
from polymigrate.migration.python_go_target import PythonToGoTargetAdapter
from polymigrate.migration.python_typescript_target import PythonToTypeScriptTargetAdapter
from polymigrate.migration.typescript_python_target import TypeScriptToPythonTargetAdapter


class DeterministicBidirectionalEquivalenceTests(unittest.TestCase):
    def _migrate(self, root: Path, source_language: str, target_language: str, source_text: str):
        extensions = {"python": ".py", "go": ".go", "typescript": ".ts"}
        source = root / "source"
        source.mkdir()
        source_path = source / ("main" + extensions[source_language])
        source_path.write_text(source_text, encoding="utf-8")
        output = root / "generated"
        registry = AdapterRegistry()
        registry.register_source(InventorySourceAdapter(source_language, (extensions[source_language],)))
        targets = {
            ("python", "go"): PythonToGoTargetAdapter,
            ("go", "python"): GoToPythonTargetAdapter,
            ("python", "typescript"): PythonToTypeScriptTargetAdapter,
            ("typescript", "python"): TypeScriptToPythonTargetAdapter,
        }
        registry.register_target(targets[(source_language, target_language)]())
        result = MigrationEngine(registry).execute(source, source_language, target_language, output)
        self.assertEqual(result.status, "GENERATED_UNVERIFIED")
        return source_path, output / ("main" + extensions[target_language])

    def _run(self, language: str, path: Path, root: Path, label: str) -> str:
        if language == "python":
            command = [sys.executable, str(path)]
            env = None
        elif language == "go":
            command = ["go", "run", str(path)]
            env = dict(os.environ, GO111MODULE="off", GOTOOLCHAIN="local")
        else:
            compiled = root / (label + "-compiled")
            compiled.mkdir()
            result = subprocess.run(
                [shutil.which("tsc"), "--strict", "--target", "ES2020", "--module", "commonjs",
                 "--outDir", str(compiled), str(path)],
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            command = [shutil.which("node"), str(compiled / "main.js")]
            env = None
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_python_to_go_preserves_arithmetic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, generated = self._migrate(root, "python", "go", "print(7 * 6)\\n")
            self.assertEqual(self._run("python", source, root, "source"), self._run("go", generated, root, "target"))

    @unittest.skipUnless(shutil.which("go"), "Go toolchain is required")
    def test_go_to_python_preserves_arithmetic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_text = 'package main\\nimport "fmt"\\nfunc main() { fmt.Println(7 * 6) }\\n'
            source, generated = self._migrate(root, "go", "python", source_text)
            self.assertEqual(self._run("go", source, root, "source"), self._run("python", generated, root, "target"))

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node"), "TypeScript compiler and Node.js are required")
    def test_python_to_typescript_preserves_arithmetic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, generated = self._migrate(root, "python", "typescript", "print(7 * 6)\\n")
            self.assertEqual(self._run("python", source, root, "source"), self._run("typescript", generated, root, "target"))

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node"), "TypeScript compiler and Node.js are required")
    def test_typescript_to_python_preserves_arithmetic_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, generated = self._migrate(root, "typescript", "python", "console.log(7 * 6);\\n")
            self.assertEqual(self._run("typescript", source, root, "source"), self._run("python", generated, root, "target"))


if __name__ == "__main__":
    unittest.main()
