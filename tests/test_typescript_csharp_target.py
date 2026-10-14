"""Runtime-equivalence tests for the bounded deterministic TypeScript-to-C# adapter."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_python_target import UnsupportedJavaScriptSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine, SourceProject, SourceUnit
from polymigrate.migration.typescript_csharp_target import TypeScriptToCSharpTargetAdapter


class TypeScriptToCSharpTargetTests(unittest.TestCase):
    def _compare_stdout(self, source_text: str):
        tsc, node, dotnet = shutil.which("tsc"), shutil.which("node"), shutil.which("dotnet")
        if not tsc or not node or not dotnet:
            self.skipTest("TypeScript compiler, Node.js, and .NET SDK are required")
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
            registry.register_target(TypeScriptToCSharpTargetAdapter())
            output = root / "generated"
            result = MigrationEngine(registry).execute(source, "typescript", "csharp", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            project = output / "PolyMigrate.csproj"
            self.assertTrue(project.is_file())
            self.assertTrue((output / "main.cs").is_file())
            build = subprocess.run(
                [dotnet, "build", str(project), "--nologo", "--verbosity", "quiet"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            generated = subprocess.run(
                [dotnet, str(output / "bin" / "Debug" / "net8.0" / "PolyMigrate.dll")],
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(original.stdout, generated.stdout)
        self.assertEqual(generated.returncode, 0, generated.stderr)

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node") and shutil.which("dotnet"),
                         "TypeScript compiler, Node.js, and .NET SDK are required")
    def test_arithmetic_and_typed_multi_argument_output_match(self):
        self._compare_stdout('const count: number = 6;\nconsole.log("value=", count * 7);\n')

    @unittest.skipUnless(shutil.which("tsc") and shutil.which("node") and shutil.which("dotnet"),
                         "TypeScript compiler, Node.js, and .NET SDK are required")
    def test_if_else_and_bounded_loop_output_match(self):
        self._compare_stdout(
            "const count: number = 2;\n"
            'if (count > 1) { console.log("many"); } else { console.log("few"); }\n'
            "for (let i = 0; i < 3; i++) { console.log(i); }\n"
        )

    def test_boolean_literals_are_rejected_to_avoid_output_drift(self):
        source = "const enabled: boolean = true;\nconsole.log(enabled);\n"
        project = SourceProject(
            Path("."),
            "typescript",
            (SourceUnit("main.ts", source, hashlib.sha256(source.encode()).hexdigest()),),
        )
        with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "Boolean literals are excluded"):
            TypeScriptToCSharpTargetAdapter().generate(project, {})

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
            TypeScriptToCSharpTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
