"""Runtime-equivalence tests for the bounded deterministic JavaScript-to-Ruby adapter."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_ruby_target import JavaScriptToRubyTargetAdapter, UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class JavaScriptToRubyTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str) -> None:
        node, ruby = shutil.which("node"), shutil.which("ruby")
        if not node or not ruby:
            self.skipTest("Node.js and Ruby toolchains are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            js_file = source / "main.js"
            js_file.write_text(source_text, encoding="utf-8")
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("javascript", (".js", ".mjs", ".cjs")))
            registry.register_target(JavaScriptToRubyTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "javascript", "ruby", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            ruby_file = output / "main.rb"
            self.assertTrue(ruby_file.is_file())
            original = subprocess.run([node, str(js_file)], capture_output=True, text=True, timeout=30)
            self.assertEqual(original.returncode, 0, original.stderr)
            syntax = subprocess.run([ruby, "-c", str(ruby_file)], cwd=output, capture_output=True, text=True, timeout=30)
            self.assertEqual(syntax.returncode, 0, syntax.stdout + syntax.stderr)
            generated = subprocess.run([ruby, str(ruby_file)], cwd=output, capture_output=True, text=True, timeout=30)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("node") and shutil.which("ruby"), "Node.js and Ruby toolchains are required")
    def test_arithmetic_and_multiple_console_arguments_match(self):
        self._compare_stdout('let count = 6;\nconsole.log("value=", count * 7);\n')

    @unittest.skipUnless(shutil.which("node") and shutil.which("ruby"), "Node.js and Ruby toolchains are required")
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
            JavaScriptToRubyTargetAdapter().generate(project, {})

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
            JavaScriptToRubyTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
