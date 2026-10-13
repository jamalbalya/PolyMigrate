"""Runtime-equivalence tests for the bounded deterministic Go-to-PHP adapter."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_php_target import GoToPHPTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class GoToPHPTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        go, php = shutil.which("go"), shutil.which("php")
        if not go or not php:
            self.skipTest("Go and PHP CLI are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            go_file = source / "main.go"
            go_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("go", (".go",)))
            registry.register_target(GoToPHPTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "go", "php", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            php_file = output / "main.php"
            self.assertTrue(php_file.is_file())
            env = dict(os.environ, GO111MODULE="off", GOTOOLCHAIN="local", GOPROXY="off")
            original = subprocess.run([go, "run", str(go_file)], capture_output=True, text=True, env=env, timeout=60)
            lint = subprocess.run([php, "-l", str(php_file)], capture_output=True, text=True, timeout=15)
            target = subprocess.run([php, str(php_file)], capture_output=True, text=True, timeout=15)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(lint.returncode, 0, lint.stderr + lint.stdout)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    @unittest.skipUnless(shutil.which("go") and shutil.which("php"), "Go and PHP CLI are required")
    def test_arithmetic_stdout_matches(self):
        self._compare_stdout('package main\nimport "fmt"\nfunc main() { count := 6; fmt.Println(count * 7) }\n')

    @unittest.skipUnless(shutil.which("go") and shutil.which("php"), "Go and PHP CLI are required")
    def test_multiple_print_arguments_match(self):
        self._compare_stdout('package main\nimport "fmt"\nfunc main() { fmt.Println("value=", 42) }\n')

    @unittest.skipUnless(shutil.which("go") and shutil.which("php"), "Go and PHP CLI are required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\n'
            'count := 2\nif count > 1 { fmt.Println("many") } else { fmt.Println("few") }\n'
            'for i := 0; i < 3; i++ { fmt.Println(i) }\n}\n'
        )

    def test_boolean_output_is_rejected_to_avoid_semantic_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text(
                'package main\nimport "fmt"\nfunc main() { fmt.Println(true) }\n', encoding="utf-8"
            )
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("go", (".go",)))
            registry.register_target(GoToPHPTargetAdapter())
            with self.assertRaisesRegex(UnsupportedGoSyntax, "Boolean literals are excluded"):
                MigrationEngine(registry).execute(source, "go", "php", root / "generated")

    def test_multiple_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text('package main\nimport "fmt"\nfunc main() { fmt.Println(1) }\n', encoding="utf-8")
            (source / "extra.go").write_text("package main\n", encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("go", (".go",)))
            registry.register_target(GoToPHPTargetAdapter())
            with self.assertRaisesRegex(UnsupportedGoSyntax, "exactly one source file"):
                MigrationEngine(registry).execute(source, "go", "php", root / "generated")


if __name__ == "__main__":
    unittest.main()
