"""Runtime-equivalence tests for the bounded deterministic JavaScript-to-Rust adapter."""
import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_rust_target import JavaScriptToRustTargetAdapter, UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class JavaScriptToRustTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        node, cargo = shutil.which("node"), shutil.which("cargo")
        if not node or not cargo:
            self.skipTest("Node.js and Rust Cargo toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            js_file = source / "main.js"
            js_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("javascript", (".js",)))
            registry.register_target(JavaScriptToRustTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "javascript", "rust", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertTrue((output / "Cargo.toml").is_file())
            self.assertTrue((output / "src" / "main.rs").is_file())
            env = dict(os.environ, CARGO_NET_OFFLINE="true")
            original = subprocess.run([node, str(js_file)], capture_output=True, text=True, env=env, timeout=30)
            target = subprocess.run([cargo, "run", "--offline", "--quiet"], cwd=output, capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    @unittest.skipUnless(shutil.which("node") and shutil.which("cargo"), "Node.js and Rust Cargo toolchains are required")
    def test_arithmetic_and_multiple_console_log_arguments_match(self):
        self._compare_stdout('const count = 6;\nconsole.log("value=", count * 7);\n')

    @unittest.skipUnless(shutil.which("node") and shutil.which("cargo"), "Node.js and Rust Cargo toolchains are required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            'let count = 2;\nif (count > 1) {\nconsole.log("many");\n} else {\nconsole.log("few");\n}\n'
            'for (let i = 0; i < 3; i++) {\nconsole.log(i);\n}\n'
        )

    def test_boolean_output_is_rejected_to_avoid_semantic_drift(self):
        source = 'console.log(true);\n'
        project = SourceProject(
            Path("."),
            "javascript",
            (SourceUnit("main.js", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "Boolean literals are excluded"):
            JavaScriptToRustTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        source = 'console.log(1);\n'
        project = SourceProject(
            Path("."),
            "javascript",
            (
                SourceUnit("main.js", source, hashlib.sha256(source.encode()).hexdigest()),
                SourceUnit("extra.js", "console.log(2);\n", hashlib.sha256(b"console.log(2);\n").hexdigest()),
            ),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "exactly one root main.js"):
            JavaScriptToRustTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
