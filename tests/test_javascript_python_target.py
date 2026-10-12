"""Tests for the bounded JavaScript-to-Python deterministic translator."""
import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.javascript_python_target import (
    JavaScriptToPythonTargetAdapter,
    UnsupportedJavaScriptSyntax,
)
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class JavaScriptToPythonTargetTests(unittest.TestCase):
    def test_translates_scalar_statements_and_preserves_console_log_output(self):
        source_text = """const count = 2 * 3 + 1;
let label = "items";
let enabled = true;
console.log(label, count, enabled);
label = label + " total";
console.log(label, false);
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.js").write_text(source_text, encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("javascript", (".js", ".mjs", ".cjs")))
            target = JavaScriptToPythonTargetAdapter()
            adapters.register_target(target)
            result = MigrationEngine(adapters).execute(
                source, "javascript", "python", root / "out",
            )
            generated = root / "out" / "main.py"
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertTrue(generated.is_file())
            code = generated.read_text(encoding="utf-8")
            ast.parse(code)
            completed = subprocess.run(
                [sys.executable, str(generated)], capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "items 7 true\nitems total false\n")

    def test_rejects_const_reassignment_and_undeclared_assignment(self):
        adapter = JavaScriptToPythonTargetAdapter()
        for source in (
            'const count = 1;\ncount = 2;\n',
            'count = 2;\n',
        ):
            with self.subTest(source=source), self.assertRaises(UnsupportedJavaScriptSyntax):
                from polymigrate.migration.javascript_python_target import _Parser
                _Parser(source).parse()

    def test_rejects_dynamic_coercion_control_flow_and_unsafe_integer(self):
        from polymigrate.migration.javascript_python_target import _Parser
        unsupported = (
            'let value = "count: " + 3;\n',
            'while (true) { console.log("unsafe"); }\n',
            'const value = 9007199254740992;\n',
            'console.log(process.env.SECRET);\n',
            'const true = 1;\n',
            'const console = 1;\n',
            'const message = "line\\nfeed";\n',
        )
        for source in unsupported:
            with self.subTest(source=source), self.assertRaises(UnsupportedJavaScriptSyntax):
                _Parser(source).parse()

    def test_rejects_type_changes_and_const_redeclarations(self):
        from polymigrate.migration.javascript_python_target import _Parser
        for source in (
            'let value = 1;\nvalue = "one";\n',
            'let value = 1;\nlet value = 2;\n',
        ):
            with self.subTest(source=source), self.assertRaises(UnsupportedJavaScriptSyntax):
                _Parser(source).parse()

    def test_translates_print_only_if_else_and_scalar_comparisons(self):
        source = '''const count = 2;
if (count > 1) { console.log("many"); } else { console.log("few"); }
if (count === 2) { console.log(true); }
if (false) { console.log("unreachable"); }
'''
        from polymigrate.migration.javascript_python_target import _Parser
        generated = _Parser(source).parse()
        ast.parse(generated)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "main.py"
            target.write_text(generated, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(target)], capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "many\ntrue\n")

    def test_rejects_assignment_nested_control_flow_and_string_ordering_in_branches(self):
        from polymigrate.migration.javascript_python_target import _Parser
        unsupported = (
            'let value = 1; if (value > 0) { value = 2; }\n',
            'if (true) { if (false) { console.log("nested"); } }\n',
            'if ("a" < "b") { console.log("ordered"); }\n',
            'if (1 < 2 < 3) { console.log("chained"); }\n',
            'if (true) { console.log("then"); }; else { console.log("else"); }\n',
        )
        for source in unsupported:
            with self.subTest(source=source), self.assertRaises(UnsupportedJavaScriptSyntax):
                _Parser(source).parse()

    def test_translates_bounded_ascending_and_descending_for_loops(self):
        source = '''for (let i = 0; i < 3; i++) { console.log(i); }
for (let j = 3; j > 0; j--) { console.log("tick", j); }
'''
        from polymigrate.migration.javascript_python_target import _Parser
        generated = _Parser(source).parse()
        ast.parse(generated)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "main.py"
            target.write_text(generated, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(target)], capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "0\n1\n2\ntick 3\ntick 2\ntick 1\n")

    def test_rejects_unsafe_for_loop_shapes_and_scope_leaks(self):
        from polymigrate.migration.javascript_python_target import _Parser
        unsupported = (
            'for (let i = 0; i < 10001; i++) { console.log(i); }\n',
            'for (let i = 0; i < 3; i--) { console.log(i); }\n',
            'for (let i = 0; i < 3; i++) { console.log(i + 1); }\n',
            'for (let i = 0; i < 3; i++) { i = 4; }\n',
            'for (let i = 0; i < 3; i++) { console.log(i); }\nconsole.log(i);\n',
        )
        for source in unsupported:
            with self.subTest(source=source), self.assertRaises(UnsupportedJavaScriptSyntax):
                _Parser(source).parse()

    def test_rejects_jsx_instead_of_mislabeling_it_as_javascript(self):
        from polymigrate.migration.pipeline import SourceProject, SourceUnit
        import hashlib
        source = "const view = <div>Hello</div>;"
        project = SourceProject(Path("."), "javascript", (
            SourceUnit("view.jsx", source, hashlib.sha256(source.encode()).hexdigest()),
        ))
        with self.assertRaises(UnsupportedJavaScriptSyntax):
            JavaScriptToPythonTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
