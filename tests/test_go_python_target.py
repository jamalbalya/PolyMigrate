"""Tests for the constrained Go-to-Python deterministic translator."""
import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.go_python_target import GoToPythonTargetAdapter, UnsupportedGoSyntax
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class GoToPythonTargetTests(unittest.TestCase):
    def test_translates_scalar_main_and_preserves_fmt_println_output(self):
        source_text = '''package main
import "fmt"

func main() {
    count := 6
    var factor int = 7
    total := count * factor
    fmt.Println("total", total)
    fmt.Println(true)
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.go").write_text(source_text, encoding="utf-8")
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("go", (".go",)))
            target = GoToPythonTargetAdapter()
            adapters.register_target(target)
            result = MigrationEngine(adapters).execute(source, "go", "python", root / "out")
            generated = root / "out" / "main.py"
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertTrue(generated.is_file())
            code = generated.read_text(encoding="utf-8")
            ast.parse(code)
            completed = subprocess.run(
                [sys.executable, str(generated)], capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "total 42\ntrue\n")

    def test_rejects_unsupported_syntax_and_invalid_go_shapes(self):
        from polymigrate.migration.go_python_target import _Parser
        unsupported = (
            'package other\nfunc main() {}\n',
            'package main\nimport "os"\nfunc main() {}\n',
            'package main\nimport "fmt"\nfunc main() {\n    unused := 1\n    fmt.Println("ok")\n}\n',
            'package main\nimport "fmt"\nfunc main() { fmt.Println("escaped\\\\nstring") }\n',
            'package main\nfunc main() { fmt.Println("missing import") }\n',
            'package main\nfunc main() { if true { fmt.Println("no") } }\n',
        )
        for source in unsupported:
            with self.subTest(source=source), self.assertRaises(UnsupportedGoSyntax):
                _Parser(source).parse()

    def test_rejects_unused_fmt_import_and_type_changing_assignment(self):
        from polymigrate.migration.go_python_target import _Parser
        for source in (
            'package main\nimport "fmt"\nfunc main() {}\n',
            'package main\nfunc main() {\n    value := 1\n    value = "one"\n    fmt.Println(value)\n}\n',
        ):
            with self.subTest(source=source), self.assertRaises(UnsupportedGoSyntax):
                _Parser(source).parse()

    def test_translates_print_only_if_else_and_bounded_for_loop(self):
        source = '''package main
import "fmt"
func main() {
    count := 2
    if count > 1 { fmt.Println("many") } else { fmt.Println("few") }
    for i := 0; i < 3; i++ { fmt.Println(i) }
}
'''
        from polymigrate.migration.go_python_target import _Parser
        generated = _Parser(source).parse()
        ast.parse(generated)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "main.py"
            target.write_text(generated, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(target)], capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "many\n0\n1\n2\n")

    def test_rejects_unsafe_go_control_flow_and_loop_shapes(self):
        from polymigrate.migration.go_python_target import _Parser
        unsupported = (
            'package main\nfunc main() { count := 1; if count { fmt.Println("bad") } }\n',
            'package main\nimport "fmt"\nfunc main() { for i := 0; i < 10001; i++ { fmt.Println(i) } }\n',
            'package main\nimport "fmt"\nfunc main() { for i := 0; i < 3; i-- { fmt.Println(i) } }\n',
            'package main\nimport "fmt"\nfunc main() { for i := 0; i < 3; i++ { fmt.Println(i + 1) } }\n',
            'package main\nimport "fmt"\nfunc main() { for i := 0; i < 3; i++ { fmt.Println(i) }\n fmt.Println(i)\n}\n',
            'package main\nimport "fmt"\nfunc main() { for i := 0; i <= 9223372036854775807; i++ { fmt.Println(i) } }\n',
        )
        for source in unsupported:
            with self.subTest(source=source), self.assertRaises(UnsupportedGoSyntax):
                _Parser(source).parse()

    def test_adapter_requires_single_root_main_go(self):
        from polymigrate.migration.pipeline import SourceProject, SourceUnit
        import hashlib
        text = "package main\nfunc main() {}\n"
        project = SourceProject(Path("."), "go", (
            SourceUnit("cmd/main.go", text, hashlib.sha256(text.encode()).hexdigest()),
        ))
        with self.assertRaises(UnsupportedGoSyntax):
            GoToPythonTargetAdapter().generate(project, {})


if __name__ == "__main__":
    unittest.main()
