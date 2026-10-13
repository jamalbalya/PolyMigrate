"""Runtime-equivalence tests for the bounded deterministic TypeScript-to-Rust adapter."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit
from polymigrate.migration.typescript_rust_target import TypeScriptToRustTargetAdapter


class TypeScriptToRustTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        tsc, node, cargo = shutil.which("tsc"), shutil.which("node"), shutil.which("cargo")
        if not tsc or not node or not cargo:
            self.skipTest("TypeScript compiler, Node.js, and Rust Cargo toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            ts_file = source / "main.ts"
            ts_file.write_text(source_text, encoding="utf-8")
            original_build = root / "original-build"
            compile_original = subprocess.run(
                [tsc, "--strict", "--target", "ES2020", "--module", "commonjs",
                 "--outDir", str(original_build), str(ts_file)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(compile_original.returncode, 0, compile_original.stdout + compile_original.stderr)
            original = subprocess.run(
                [node, str(original_build / "main.js")], capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(original.returncode, 0, original.stderr)

            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("typescript", (".ts",)))
            registry.register_target(TypeScriptToRustTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "typescript", "rust", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertTrue((output / "Cargo.toml").is_file())
            self.assertTrue((output / "src" / "main.rs").is_file())
            env = dict(os.environ, CARGO_NET_OFFLINE="true")
            target = subprocess.run(
                [cargo, "run", "--offline", "--quiet"], cwd=output,
                capture_output=True, text=True, env=env, timeout=120,
            )
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node") and shutil.which("cargo"),
                         "TypeScript compiler, Node.js, and Rust Cargo toolchains are required")
    def test_arithmetic_and_typed_multi_argument_output_match(self):
        self._compare_stdout('const count: number = 6;\nconsole.log("value=", count * 7);\n')

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node") and shutil.which("cargo"),
                         "TypeScript compiler, Node.js, and Rust Cargo toolchains are required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            "const count: number = 2;\n"
            'if (count > 1) { console.log("many"); } else { console.log("few"); }\n'
            "for (let i = 0; i < 3; i++) { console.log(i); }\n"
        )

    def test_boolean_literals_are_rejected_to_avoid_semantic_drift(self):
        source = "const enabled: boolean = true;\nconsole.log(enabled);\n"
        project = SourceProject(
            Path("."),
            "typescript",
            (SourceUnit("main.ts", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "Boolean literals are excluded"):
            TypeScriptToRustTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        source = "console.log(1);\n"
        project = SourceProject(
            Path("."),
            "typescript",
            (
                SourceUnit("main.ts", source, hashlib.sha256(source.encode()).hexdigest()),
                SourceUnit("extra.ts", source, hashlib.sha256(source.encode()).hexdigest()),
            ),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "exactly one root main.ts"):
            TypeScriptToRustTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
