"""Runtime-equivalence tests for the bounded deterministic TypeScript-to-Kotlin adapter."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit
from polymigrate.migration.typescript_kotlin_target import TypeScriptToKotlinTargetAdapter

class TypeScriptToKotlinTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        tsc, node, kotlinc, java = (shutil.which("tsc"), shutil.which("node"), shutil.which("kotlinc"), shutil.which("java"))
        if not all((tsc, node, kotlinc, java)):
            self.skipTest("TypeScript compiler, Node.js, kotlinc, and Java are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / "source"; source.mkdir()
            ts_file = source / "main.ts"; ts_file.write_text(source_text, encoding="utf-8")
            original_build = root / "original-build"
            compiled_ts = subprocess.run([tsc, "--strict", "--target", "ES2020", "--module", "commonjs", "--outDir", str(original_build), str(ts_file)], capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled_ts.returncode, 0, compiled_ts.stdout + compiled_ts.stderr)
            original = subprocess.run([node, str(original_build / "main.js")], capture_output=True, text=True, timeout=30)
            self.assertEqual(original.returncode, 0, original.stderr)
            registry = AdapterRegistry()
            registry.register_source(InventorySourceAdapter("typescript", (".ts",)))
            registry.register_target(TypeScriptToKotlinTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "typescript", "kotlin", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            kotlin_file = output / "Main.kt"; self.assertTrue(kotlin_file.is_file())
            jar_file = output / "app.jar"
            compiled_kotlin = subprocess.run([kotlinc, str(kotlin_file), "-include-runtime", "-d", str(jar_file)], cwd=output, capture_output=True, text=True, timeout=180)
            self.assertEqual(compiled_kotlin.returncode, 0, compiled_kotlin.stderr)
            generated = subprocess.run([java, "-jar", str(jar_file)], cwd=output, capture_output=True, text=True, timeout=30)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node") and shutil.which("kotlinc") and shutil.which("java"), "TypeScript compiler, Node.js, Kotlin compiler, and Java are required")
    def test_typed_arithmetic_and_multiple_arguments_match(self):
        self._compare_stdout('const count: number = 6;\nconsole.log("value=", count * 7);\n')

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node") and shutil.which("kotlinc") and shutil.which("java"), "TypeScript compiler, Node.js, Kotlin compiler, and Java are required")
    def test_if_else_output_matches(self):
        self._compare_stdout("const count: number = 2;\nif (count > 1) { console.log(\"many\"); } else { console.log(\"few\"); }\n")

    def test_boolean_literals_are_rejected(self):
        source = "const enabled: boolean = true;\nconsole.log(enabled);\n"
        project = SourceProject(Path("."), "typescript", (SourceUnit("main.ts", source, hashlib.sha256(source.encode()).hexdigest()),))
        with self.assertRaises(UnsupportedJavaScriptSyntax):
            TypeScriptToKotlinTargetAdapter().generate(project, {})

    def test_multiple_files_are_rejected(self):
        source = "console.log(1);\n"
        project = SourceProject(Path("."), "typescript", (SourceUnit("main.ts", source, hashlib.sha256(source.encode()).hexdigest()), SourceUnit("extra.ts", source, hashlib.sha256(source.encode()).hexdigest())))
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "exactly one root main.ts"):
            TypeScriptToKotlinTargetAdapter().generate(project, {})

if __name__ == "__main__":
    unittest.main()
