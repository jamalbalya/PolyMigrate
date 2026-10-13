"""Runtime-equivalence tests for the bounded deterministic Go-to-Rust adapter."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_rust_target import GoToRustTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class GoToRustTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        go, cargo = shutil.which("go"), shutil.which("cargo")
        if not go or not cargo:
            self.skipTest("Go and Rust Cargo toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            go_file = source / "main.go"
            go_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("go", (".go",)))
            registry.register_target(GoToRustTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "go", "rust", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            cargo_file = output / "Cargo.toml"
            rust_file = output / "src" / "main.rs"
            self.assertTrue(cargo_file.is_file())
            self.assertTrue(rust_file.is_file())
            env = dict(os.environ, GOTOOLCHAIN="local", GOPROXY="off", GO111MODULE="off", CARGO_NET_OFFLINE="true")
            original = subprocess.run([go, "run", str(go_file)], capture_output=True, text=True, env=env, timeout=60)
            target = subprocess.run([cargo, "run", "--offline", "--quiet"], cwd=output, capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    @unittest.skipUnless(shutil.which("go") and shutil.which("cargo"), "Go and Rust Cargo toolchains are required")
    def test_arithmetic_and_multiple_print_arguments_match(self):
        self._compare_stdout('package main\nimport "fmt"\nfunc main() {\ncount := 6\nfmt.Println("value=", count * 7)\n}\n')

    @unittest.skipUnless(shutil.which("go") and shutil.which("cargo"), "Go and Rust Cargo toolchains are required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            'package main\nimport "fmt"\nfunc main() {\n'
            'count := 2\nif count > 1 {\nfmt.Println("many")\n} else {\nfmt.Println("few")\n}\n'
            'for i := 0; i < 3; i++ {\nfmt.Println(i)\n}\n}\n'
        )

    def test_boolean_output_is_rejected_to_avoid_semantic_drift(self):
        source = 'package main\nimport "fmt"\nfunc main() {\nfmt.Println(true)\n}\n'
        project = SourceProject(
            Path("."),
            "go",
            (SourceUnit("main.go", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedGoSyntax, "Boolean literals are excluded"):
            GoToRustTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        source = 'package main\nimport "fmt"\nfunc main() {\nfmt.Println(1)\n}\n'
        project = SourceProject(
            Path("."),
            "go",
            (
                SourceUnit("main.go", source, hashlib.sha256(source.encode()).hexdigest()),
                SourceUnit("extra.go", "package main\n", hashlib.sha256(b"package main\n").hexdigest()),
            ),
        )
        with self.assertRaisesRegex(UnsupportedGoSyntax, "exactly one root main.go"):
            GoToRustTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
