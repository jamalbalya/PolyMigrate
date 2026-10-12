"""Tests for the bounded deterministic JavaScript-to-C# adapter."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_csharp_target import (
    JavaScriptToCSharpTargetAdapter,
    UnsupportedJavaScriptSyntax,
)
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class JavaScriptToCSharpTargetTests(unittest.TestCase):
    def _migrate(self, source_text: str, root: Path):
        source = root / "source"
        source.mkdir()
        (source / "main.js").write_text(source_text, encoding="utf-8")
        adapters = AdapterRegistry()
        adapters.register_source(InventorySourceAdapter("javascript", (".js", ".mjs", ".cjs")))
        adapters.register_target(JavaScriptToCSharpTargetAdapter())
        output = root / "generated"
        result = MigrationEngine(adapters).execute(source, "javascript", "csharp", output)
        return result, source / "main.js", output

    def _compare_stdout(self, source_text: str):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result, source, output = self._migrate(source_text, root)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            original = subprocess.run(["node", str(source)], capture_output=True, text=True, timeout=30)
            project = output / "PolyMigrate.csproj"
            build = subprocess.run(
                ["dotnet", "build", str(project), "--nologo", "--verbosity", "quiet"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            generated = subprocess.run(
                ["dotnet", str(output / "bin" / "Debug" / "net8.0" / "PolyMigrate.dll")],
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("node") and shutil.which("dotnet"), "Node.js and .NET SDK are required")
    def test_arithmetic_output_matches(self):
        self._compare_stdout("const count = 6;\nconsole.log(count * 7);\n")

    @unittest.skipUnless(shutil.which("node") and shutil.which("dotnet"), "Node.js and .NET SDK are required")
    def test_multiple_print_arguments_match(self):
        self._compare_stdout('console.log("value=", 42);\n')

    @unittest.skipUnless(shutil.which("node") and shutil.which("dotnet"), "Node.js and .NET SDK are required")
    def test_if_else_and_bounded_loop_output_match(self):
        self._compare_stdout(
            'const count = 2;\n'
            'if (count > 1) { console.log("many"); } else { console.log("few"); }\n'
            'for (let i = 0; i < 3; i++) { console.log(i); }\n'
        )

    def test_boolean_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text("console.log(true);\n", encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("javascript", (".js",)))
            adapters.register_target(JavaScriptToCSharpTargetAdapter())
            with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "Boolean literals are intentionally excluded"):
                MigrationEngine(adapters).execute(source, "javascript", "csharp", root / "generated")

    def test_multiple_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text("console.log(1);\n", encoding="utf-8")
            (source / "extra.js").write_text("console.log(2);\n", encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("javascript", (".js",)))
            adapters.register_target(JavaScriptToCSharpTargetAdapter())
            with self.assertRaisesRegex(UnsupportedJavaScriptSyntax, "exactly one source file"):
                MigrationEngine(adapters).execute(source, "javascript", "csharp", root / "generated")


if __name__ == "__main__":
    unittest.main()
