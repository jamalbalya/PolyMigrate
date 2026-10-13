"""Runtime-equivalence tests for the bounded TypeScript-to-Go adapter."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine
from polymigrate.migration.typescript_go_target import TypeScriptToGoTargetAdapter


class TypeScriptToGoTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        tsc, node, go = shutil.which("tsc"), shutil.which("node"), shutil.which("go")
        if not tsc or not node or not go:
            self.skipTest("TypeScript compiler, Node.js, and Go toolchain are required")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.ts").write_text(source_text, encoding="utf-8")
            original_build = root / "original-build"
            compile_original = subprocess.run(
                [tsc, "--strict", "--target", "ES2020", "--module", "commonjs",
                 "--outDir", str(original_build), str(source / "main.ts")],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(compile_original.returncode, 0, compile_original.stdout + compile_original.stderr)
            original = subprocess.run(
                [node, str(original_build / "main.js")], capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(original.returncode, 0, original.stderr)

            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("typescript", (".ts",)))
            adapters.register_target(TypeScriptToGoTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(adapters).execute(source, "typescript", "go", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            generated = output / "main.go"
            self.assertTrue(generated.is_file())
            target = subprocess.run(
                [go, "run", str(generated)], capture_output=True, text=True, timeout=120,
                env={**__import__("os").environ, "GOTOOLCHAIN": "local", "GOPROXY": "off", "GO111MODULE": "off"},
            )
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertEqual(original.stdout, target.stdout)

    def test_arithmetic_stdout_matches(self):
        self._compare_stdout("const count: number = 6;\nconsole.log(count * 7);\n")

    def test_multi_argument_output_matches(self):
        self._compare_stdout('console.log("value=", 42);\n')

    def test_if_else_and_bounded_loop_output_matches(self):
        self._compare_stdout(
            "const count: number = 2;\n"
            'if (count > 1) { console.log("many"); } else { console.log("few"); }\n'
            "for (let i = 0; i < 3; i++) { console.log(i); }\n"
        )

    def test_boolean_literals_are_rejected_to_prevent_output_drift(self):
        from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
        import hashlib
        from polymigrate.migration.pipeline import SourceProject, SourceUnit
        source = "const enabled: boolean = true;\nconsole.log(enabled);\n"
        project = SourceProject(
            Path("."),
            "typescript",
            (SourceUnit("main.ts", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "Boolean literals are excluded"):
            TypeScriptToGoTargetAdapter().generate(project, {})

    def test_rejects_multiple_files(self):
        from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
        import hashlib
        from polymigrate.migration.pipeline import SourceProject, SourceUnit
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
            TypeScriptToGoTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
