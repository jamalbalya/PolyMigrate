"""Tests for the bounded deterministic JavaScript-to-Go adapter."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_go_target import JavaScriptToGoTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class JavaScriptToGoTargetTests(unittest.TestCase):
    def _migrate(self, source_text: str, root: Path):
        source = root / "source"
        source.mkdir()
        (source / "main.js").write_text(source_text, encoding="utf-8")
        adapters = AdapterRegistry()
        adapters.register_source(InventorySourceAdapter("javascript", (".js",)))
        adapters.register_target(JavaScriptToGoTargetAdapter())
        output = root / "generated"
        result = MigrationEngine(adapters).execute(source, "javascript", "go", output)
        return result, source / "main.js", output / "main.go"

    @unittest.skipUnless(shutil.which("node") and shutil.which("go"), "Node.js and Go are required")
    def test_console_log_arithmetic_preserves_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, source, generated = self._migrate(
                "const count = 6;\nconsole.log(count * 7);\n", root
            )
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            original = subprocess.run(["node", str(source)], capture_output=True, text=True, timeout=30)
            env = dict(os.environ, GO111MODULE="off", GOTOOLCHAIN="local")
            target = subprocess.run(["go", "run", str(generated)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    @unittest.skipUnless(shutil.which("node") and shutil.which("go"), "Node.js and Go are required")
    def test_string_and_boolean_output_preserve_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, source, generated = self._migrate(
                'console.log("value=" + String(42));\nconsole.log(true);\n', root
            )
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            original = subprocess.run(["node", str(source)], capture_output=True, text=True, timeout=30)
            env = dict(os.environ, GO111MODULE="off", GOTOOLCHAIN="local")
            target = subprocess.run(["go", "run", str(generated)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    def test_multiple_files_are_rejected_by_composed_subset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text("console.log(42);\n", encoding="utf-8")
            (source / "extra.js").write_text("console.log(7);\n", encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("javascript", (".js",)))
            adapters.register_target(JavaScriptToGoTargetAdapter())
            with self.assertRaisesRegex(ValueError, "exactly one source file"):
                MigrationEngine(adapters).execute(source, "javascript", "go", root / "generated")


if __name__ == "__main__":
    unittest.main()
