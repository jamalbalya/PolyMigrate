"""Runtime-equivalence tests for the bounded JavaScript-to-TypeScript adapter."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_typescript_target import JavaScriptToTypeScriptTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class JavaScriptToTypeScriptTargetTests(unittest.TestCase):
    def _migrate(self, source_text: str, root: Path):
        source = root / "source"
        source.mkdir()
        (source / "main.js").write_text(source_text, encoding="utf-8")
        adapters = AdapterRegistry()
        adapters.register_source(InventorySourceAdapter("javascript", (".js", ".mjs", ".cjs")))
        adapters.register_target(JavaScriptToTypeScriptTargetAdapter())
        output = root / "generated"
        result = MigrationEngine(adapters).execute(source, "javascript", "typescript", output)
        return result, source / "main.js", output / "main.ts"

    def _compare_stdout(self, source_text: str):
        if not shutil.which("node") or not shutil.which("tsc"):
            self.skipTest("Node.js and TypeScript compiler are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, source, generated = self._migrate(source_text, root)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            original = subprocess.run([shutil.which("node"), str(source)], capture_output=True, text=True, timeout=30)
            self.assertEqual(original.returncode, 0, original.stderr)
            compiled_dir = root / "compiled"
            compile_result = subprocess.run(
                [shutil.which("tsc"), "--strict", "--target", "ES2020", "--module", "commonjs",
                 "--outDir", str(compiled_dir), str(generated)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            target = subprocess.run(
                [shutil.which("node"), str(compiled_dir / "main.js")],
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    def test_arithmetic_stdout_matches(self):
        self._compare_stdout("const count = 6;\nconsole.log(count * 7);\n")

    def test_multiple_arguments_stdout_matches(self):
        self._compare_stdout('console.log("value=", 42);\n')

    def test_boolean_stdout_matches(self):
        self._compare_stdout("console.log(true, false);\n")

    def test_if_else_and_bounded_loop_stdout_matches(self):
        self._compare_stdout(
            "const count = 2;\n"
            'if (count > 1) { console.log("many"); } else { console.log("few"); }\n'
            "for (let i = 0; i < 3; i++) { console.log(i); }\n"
        )

    def test_multiple_source_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text("console.log(1);\n", encoding="utf-8")
            (source / "extra.js").write_text("console.log(2);\n", encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("javascript", (".js",)))
            adapters.register_target(JavaScriptToTypeScriptTargetAdapter())
            with self.assertRaisesRegex(ValueError, "exactly one source file"):
                MigrationEngine(adapters).execute(source, "javascript", "typescript", root / "generated")


if __name__ == "__main__":
    unittest.main()
