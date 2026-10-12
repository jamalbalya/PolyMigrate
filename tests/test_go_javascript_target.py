"""Tests for the bounded deterministic Go-to-JavaScript adapter."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_javascript_target import GoToJavaScriptTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class GoToJavaScriptTargetTests(unittest.TestCase):
    def _migrate(self, source_text: str, root: Path):
        source = root / "source"
        source.mkdir()
        (source / "main.go").write_text(source_text, encoding="utf-8")
        adapters = AdapterRegistry()
        adapters.register_source(InventorySourceAdapter("go", (".go",)))
        adapters.register_target(GoToJavaScriptTargetAdapter())
        output = root / "generated"
        result = MigrationEngine(adapters).execute(source, "go", "javascript", output)
        return result, source / "main.go", output / "main.js"

    def _compare_stdout(self, source_text: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, source, generated = self._migrate(source_text, root)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            original = subprocess.run(
                ["go", "run", str(source)], capture_output=True, text=True,
                env=dict(os.environ, GO111MODULE="off", GOTOOLCHAIN="local"), timeout=60,
            )
            target = subprocess.run(["node", str(generated)], capture_output=True, text=True, timeout=30)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    @unittest.skipUnless(shutil.which("go") and shutil.which("node"), "Go and Node.js are required")
    def test_arithmetic_output_matches(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\n    count := 6\n    fmt.Println(count * 7)\n}\n'
        )

    @unittest.skipUnless(shutil.which("go") and shutil.which("node"), "Go and Node.js are required")
    def test_multiple_print_arguments_match(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() { fmt.Println("value=", 42) }\n'
        )

    @unittest.skipUnless(shutil.which("go") and shutil.which("node"), "Go and Node.js are required")
    def test_if_else_and_bounded_loop_output_match(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\n'
            '    count := 2\n'
            '    if count > 1 { fmt.Println("many") } else { fmt.Println("few") }\n'
            '    for i := 0; i < 3; i++ { fmt.Println(i) }\n'
            '}\n'
        )

    def test_boolean_output_is_rejected_to_avoid_semantic_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text(
                'package main\nimport "fmt"\nfunc main() { fmt.Println(true) }\n', encoding="utf-8",
            )
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("go", (".go",)))
            adapters.register_target(GoToJavaScriptTargetAdapter())
            with self.assertRaisesRegex(UnsupportedGoSyntax, "Boolean literals are not supported"):
                MigrationEngine(adapters).execute(source, "go", "javascript", root / "generated")

    def test_multiple_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text('package main\nimport "fmt"\nfunc main() { fmt.Println(1) }\n', encoding="utf-8")
            (source / "extra.go").write_text('package main\n', encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("go", (".go",)))
            adapters.register_target(GoToJavaScriptTargetAdapter())
            with self.assertRaisesRegex(UnsupportedGoSyntax, "exactly one source file"):
                MigrationEngine(adapters).execute(source, "go", "javascript", root / "generated")


if __name__ == "__main__":
    unittest.main()
