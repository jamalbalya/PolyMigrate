"""Runtime-equivalence tests for the bounded deterministic JavaScript-to-C++ adapter."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_cpp_target import JavaScriptToCppTargetAdapter, UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class JavaScriptToCppTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str) -> None:
        node, compiler = shutil.which("node"), shutil.which("g++")
        if not node or not compiler:
            self.skipTest("Node.js and g++ toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            js_file = source / "main.js"
            js_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("javascript", (".js", ".mjs", ".cjs")))
            registry.register_target(JavaScriptToCppTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "javascript", "cpp", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            cpp_file = output / "main.cpp"
            self.assertTrue(cpp_file.is_file())
            original = subprocess.run([node, str(js_file)], capture_output=True, text=True, timeout=30)
            self.assertEqual(original.returncode, 0, original.stderr)
            compiled = subprocess.run(
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                 str(cpp_file), "-o", str(output / "app")],
                cwd=output, capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            generated = subprocess.run([str(output / "app")], cwd=output, capture_output=True, text=True, timeout=30)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("node") and shutil.which("g++"), "Node.js and g++ toolchains are required")
    def test_arithmetic_and_multiple_console_arguments_match(self):
        self._compare_stdout('let count = 6;\nconsole.log("value=", count * 7);\n')

    @unittest.skipUnless(shutil.which("node") and shutil.which("g++"), "Node.js and g++ toolchains are required")
    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            'let count = 2;\ncount = count + 1;\n'
            'if (count > 1) {\n console.log("many");\n} else {\n console.log("few");\n}\n'
            'for (let i = 0; i < 3; i++) {\n console.log(i);\n}\n'
        )

    def test_boolean_literals_are_rejected_to_avoid_output_drift(self):
        source = "console.log(true);\n"
        project = SourceProject(
            Path("."), "javascript",
            (SourceUnit("main.js", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "Boolean literals are excluded"):
            JavaScriptToCppTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        source = 'console.log("hello");\n'
        extra = 'console.log("world");\n'
        project = SourceProject(
            Path("."), "javascript",
            (
                SourceUnit("main.js", source, hashlib.sha256(source.encode()).hexdigest()),
                SourceUnit("extra.js", extra, hashlib.sha256(extra.encode()).hexdigest()),
            ),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "exactly one root main.js"):
            JavaScriptToCppTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
