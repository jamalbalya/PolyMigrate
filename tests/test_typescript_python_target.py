"""Tests for the constrained TypeScript-to-Python deterministic translator."""
import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine
from polymigrate.migration.typescript_python_target import TypeScriptToPythonTargetAdapter, UnsupportedJavaScriptSyntax


class TypeScriptToPythonTargetTests(unittest.TestCase):
    def test_translates_primitive_annotations_if_else_and_bounded_loop(self):
        source_text = '''const count: number = 2;
let label: string = "items";
const enabled: boolean = true;
console.log(label, count * 3, enabled);
if (count > 1) { console.log("many"); } else { console.log("few"); }
for (let i = 0; i < 2; i++) { console.log(i); }
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.ts").write_text(source_text, encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("typescript", (".ts",)))
            adapters.register_target(TypeScriptToPythonTargetAdapter())
            result = MigrationEngine(adapters).execute(source, "typescript", "python", root / "out")
            generated = root / "out" / "main.py"
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertTrue(generated.is_file())
            code = generated.read_text(encoding="utf-8")
            ast.parse(code)
            completed = subprocess.run(
                [sys.executable, str(generated)], capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "items 6 true\nmany\n0\n1\n")

    def test_rejects_annotation_mismatches_and_unknown_types(self):
        from polymigrate.migration.javascript_python_target import _Parser
        unsupported = (
            'const count: string = 1;\n',
            'const count: object = 1;\n',
            'const count: number = 1.5;\n',
            'import { something } from "module";\n',
            'interface User { name: string }\n',
        )
        for source in unsupported:
            with self.subTest(source=source), self.assertRaises(UnsupportedJavaScriptSyntax):
                _Parser(source, allow_type_annotations=True).parse()

    def test_javascript_mode_does_not_accept_typescript_annotations(self):
        from polymigrate.migration.javascript_python_target import _Parser
        with self.assertRaises(UnsupportedJavaScriptSyntax):
            _Parser("const count: number = 1;\n").parse()

    def test_adapter_requires_single_root_main_ts(self):
        from polymigrate.migration.pipeline import SourceProject, SourceUnit
        import hashlib
        text = 'const count: number = 1;\nconsole.log(count);\n'
        project = SourceProject(Path("."), "typescript", (
            SourceUnit("src/main.ts", text, hashlib.sha256(text.encode()).hexdigest()),
        ))
        with self.assertRaises(UnsupportedJavaScriptSyntax):
            TypeScriptToPythonTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
