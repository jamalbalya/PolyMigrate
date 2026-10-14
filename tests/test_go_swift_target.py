"""Runtime-equivalence tests for the bounded deterministic Go-to-Swift adapter."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_swift_target import GoToSwiftTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class GoToSwiftTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str) -> None:
        go, swift = shutil.which("go"), shutil.which("swift")
        if not go or not swift:
            self.skipTest("Go and Swift toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            go_file = source / "main.go"
            go_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("go", (".go",)))
            registry.register_target(GoToSwiftTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "go", "swift", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            swift_file = output / "main.swift"
            self.assertTrue(swift_file.is_file())
            env = dict(os.environ, GOTOOLCHAIN="local", GOPROXY="off", GO111MODULE="off")
            original = subprocess.run([go, "run", str(go_file)], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(original.returncode, 0, original.stderr)
            compiled = subprocess.run([swift, "c", "-warnings-as-errors", str(swift_file), "-o", str(output / "app")],
                                      cwd=output, capture_output=True, text=True, timeout=90)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            generated = subprocess.run([str(output / "app")], cwd=output, capture_output=True, text=True, timeout=30)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("go") and shutil.which("swift"), "Go and Swift toolchains are required")
    def test_arithmetic_and_multiple_print_arguments_match(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\ncount := 6\nfmt.Println("value=", count * 7)\n}\n'
        )

    @unittest.skipUnless(shutil.which("go") and shutil.which("swift"), "Go and Swift toolchains are required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\ncount := 2\n'
            'if count > 1 {\nfmt.Println("many")\n} else {\nfmt.Println("few")\n}\n'
            'for i := 0; i < 3; i++ {\nfmt.Println(i)\n}\n}\n'
        )

    def test_boolean_literals_are_rejected_to_avoid_output_drift(self):
        source = 'package main\nimport "fmt"\nfunc main() {\nfmt.Println(true)\n}\n'
        project = SourceProject(
            Path("."), "go",
            (SourceUnit("main.go", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedGoSyntax, "Boolean literals are excluded"):
            GoToSwiftTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        source = 'package main\nimport "fmt"\nfunc main() {\nfmt.Println(1)\n}\n'
        extra = "package main\n"
        project = SourceProject(
            Path("."), "go",
            (
                SourceUnit("main.go", source, hashlib.sha256(source.encode()).hexdigest()),
                SourceUnit("extra.go", extra, hashlib.sha256(extra.encode()).hexdigest()),
            ),
        )
        with self.assertRaisesRegex(UnsupportedGoSyntax, "exactly one root main.go"):
            GoToSwiftTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
