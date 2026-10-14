"""Runtime-equivalence tests for the bounded deterministic JavaScript-to-Kotlin adapter."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_kotlin_target import JavaScriptToKotlinTargetAdapter
from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit


class JavaScriptToKotlinTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        node, kotlinc, java = shutil.which("node"), shutil.which("kotlinc"), shutil.which("java")
        if not node or not kotlinc or not java:
            self.skipTest("Node.js, kotlinc, and Java runtime are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            js_file = source / "main.js"
            js_file.write_text(source_text, encoding="utf-8")
            original = subprocess.run(
                [node, str(js_file)], capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(original.returncode, 0, original.stderr)

            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("javascript", (".js", ".mjs", ".cjs")))
            registry.register_target(JavaScriptToKotlinTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "javascript", "kotlin", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            kotlin_file = output / "Main.kt"
            self.assertTrue(kotlin_file.is_file())
            jar_file = output / "app.jar"
            compiled = subprocess.run(
                [kotlinc, str(kotlin_file), "-include-runtime", "-d", str(jar_file)],
                cwd=output, capture_output=True, text=True, timeout=180,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            generated = subprocess.run(
                [java, "-jar", str(jar_file)], cwd=output,
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("node") and shutil.which("kotlinc") and shutil.which("java"),
                         "Node.js, kotlinc, and Java runtime are required")
    def test_arithmetic_and_multiple_arguments_match(self):
        self._compare_stdout('const count = 6;\nconsole.log("value=", count * 7);\n')

    @unittest.skipUnless(shutil.which("node") and shutil.which("kotlinc") and shutil.which("java"),
                         "Node.js, kotlinc, and Java runtime are required")
    def test_if_else_output_matches(self):
        self._compare_stdout(
            'const count = 2;\n'
            'if (count > 1) { console.log("many"); } else { console.log("few"); }\n'
        )

    def test_boolean_literals_are_rejected_to_avoid_output_drift(self):
        source = "console.log(true);\n"
        project = SourceProject(
            Path("."),
            "javascript",
            (SourceUnit("main.js", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "Boolean literals are excluded"):
            JavaScriptToKotlinTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        source = "console.log(1);\n"
        project = SourceProject(
            Path("."),
            "javascript",
            (
                SourceUnit("main.js", source, hashlib.sha256(source.encode()).hexdigest()),
                SourceUnit("extra.js", source, hashlib.sha256(source.encode()).hexdigest()),
            ),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "exactly one source file"):
            JavaScriptToKotlinTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
