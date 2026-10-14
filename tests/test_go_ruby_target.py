"""Runtime-equivalence tests for the bounded deterministic Go-to-Ruby adapter."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_ruby_target import GoToRubyTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class GoToRubyTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str) -> None:
        go, ruby = shutil.which("go"), shutil.which("ruby")
        if not go or not ruby:
            self.skipTest("Go and Ruby toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            go_file = source / "main.go"
            go_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("go", (".go",)))
            registry.register_target(GoToRubyTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "go", "ruby", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            ruby_file = output / "main.rb"
            self.assertTrue(ruby_file.is_file())
            env = dict(os.environ, GOTOOLCHAIN="local", GOPROXY="off", GO111MODULE="off")
            original = subprocess.run([go, "run", str(go_file)], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(original.returncode, 0, original.stderr)
            syntax = subprocess.run([ruby, "-c", str(ruby_file)], cwd=output, capture_output=True, text=True, timeout=30)
            self.assertEqual(syntax.returncode, 0, syntax.stdout + syntax.stderr)
            generated = subprocess.run([ruby, str(ruby_file)], cwd=output, capture_output=True, text=True, timeout=30)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("go") and shutil.which("ruby"), "Go and Ruby toolchains are required")
    def test_arithmetic_and_multiple_print_arguments_match(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\ncount := 6\nfmt.Println("value=", count * 7)\n}\n'
        )

    @unittest.skipUnless(shutil.which("go") and shutil.which("ruby"), "Go and Ruby toolchains are required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\ncount := 2\ncount = count + 1\n'
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
            GoToRubyTargetAdapter().generate(project, {})

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
            GoToRubyTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
