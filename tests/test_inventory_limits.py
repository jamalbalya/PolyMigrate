"""Resource-limit tests for source inventory."""
import tempfile
import unittest
from pathlib import Path
from polymigrate.migration.adapters import InventorySourceAdapter, _tree_sitter_imports


class InventoryLimitTests(unittest.TestCase):
    def test_file_count_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("a", encoding="utf-8")
            (root / "b.py").write_text("b", encoding="utf-8")
            adapter = InventorySourceAdapter("python", (".py",), max_files=1)
            with self.assertRaisesRegex(ValueError, "file count exceeds"):
                adapter.analyze(root)

    def test_python_ast_extracts_symbols_and_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text(
                "import requests\nfrom project.helpers import parse\n"
                "class Client:\n    pass\n\ndef fetch(url):\n    return url\n",
                encoding="utf-8",
            )
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            unit = project.units[0]
            self.assertIn("Client", unit.symbols)
            self.assertIn("fetch", unit.symbols)
            self.assertIn("requests", unit.dependencies)
            self.assertIn("project.helpers", unit.dependencies)

    def test_python_parse_failure_keeps_source_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            self.assertEqual(len(project.units), 1)
            self.assertEqual(project.units[0].symbols, ())
            self.assertTrue(any("could not be parsed safely" in warning for warning in project.metadata["warnings"]))

    def test_offline_tree_sitter_reports_syntax_errors_when_grammar_is_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text("package main\\nfunc main( {\\n", encoding="utf-8")
            project = InventorySourceAdapter("go", (".go",)).analyze(root)
            if "tree-sitter" not in project.metadata["parser_backends"]:
                self.skipTest("Offline Go Tree-sitter grammar is not available")
            self.assertTrue(any("Tree-sitter reported syntax errors" in warning for warning in project.metadata["warnings"]))

    def test_go_structure_hints_include_types_functions_and_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text(
                'package main\nimport "fmt"\ntype Service struct {}\nfunc Run() {}\n',
                encoding="utf-8",
            )
            project = InventorySourceAdapter("go", (".go",)).analyze(root)
            unit = project.units[0]
            self.assertIn("Service", unit.symbols)
            self.assertIn("Run", unit.symbols)
            self.assertIn("fmt", unit.dependencies)


    def test_tree_sitter_import_nodes_ignore_comment_and_string_lookalikes(self):
        cases = {
            "rust": (
                '''// use fake::comment;
let text = "use fake::string";
use real::package;
fn main() {}
''',
                "real", "fake",
            ),
            "java": (
                '''// import fake.Comment;
import real.package.Type;
class Example { String text = "import fake.String"; }
''',
                "real.package.Type", "fake",
            ),
            "kotlin": (
                '''// import fake.Comment
import real.package.Type
val text = "import fake.String"
''',
                "real.package.Type", "fake",
            ),
            "csharp": (
                '''// using Fake.Comment;
using Real.Namespace;
class Example { string text = "using Fake.String;"; }
''',
                "Real.Namespace", "Fake",
            ),
            "cpp": (
                '''// #include "fake/comment.h"
#include <real/header.h>
const char* text = "#include fake/string.h";
''',
                "real/header.h", "fake",
            ),
            "c": (
                '''// #include "fake/comment.h"
#include <real/header.h>
const char* text = "#include fake/string.h";
''',
                "real/header.h", "fake",
            ),
            "ruby": (
                '''# require "fake/comment"
text = 'require "fake/string"'
require "real_package"
''',
                "real_package", "fake",
            ),
            "php": (
                r'''<?php
// use Fake\Comment;
use Real\Package;
$text = "use Fake\String;";
''',
                r"Real\Package", "Fake",
            ),
            "swift": (
                '''// import FakeComment
import RealModule
let text = "import FakeString"
''',
                "RealModule", "Fake",
            ),
        }
        unavailable = []
        for language, (source, expected, forbidden) in cases.items():
            with self.subTest(language=language):
                imports = _tree_sitter_imports(language, source)
                if imports is None:
                    unavailable.append(language)
                    continue
                self.assertTrue(any(expected in item for item in imports), imports)
                self.assertFalse(any(forbidden in item for item in imports), imports)
        if len(unavailable) == len(cases):
            self.skipTest("No offline Tree-sitter grammars for the import conformance matrix")

    def test_tree_sitter_go_imports_ignore_comments_and_raw_string_literals(self):
        source = '''package main
// import "fake/comment"
import (
    "fmt"
    "example.com/real"
)
var text = `import "fake/raw"`
'''
        imports = _tree_sitter_imports("go", source)
        if imports is None:
            self.skipTest("offline Go Tree-sitter grammar is unavailable")
        self.assertIn("fmt", imports)
        self.assertIn("example.com/real", imports)
        self.assertNotIn("fake/comment", imports)
        self.assertNotIn("fake/raw", imports)

    def test_tree_sitter_javascript_imports_ignore_comments_and_strings(self):
        source = '''// import fake from "fake/comment";
const text = 'require("fake/string")';
import { value } from "real-package";
export { value } from "other-package";
const cjs = require("real-cjs");
'''
        imports = _tree_sitter_imports("javascript", source)
        if imports is None:
            self.skipTest("offline JavaScript Tree-sitter grammar is unavailable")
        self.assertIn("real-package", imports)
        self.assertIn("other-package", imports)
        self.assertIn("real-cjs", imports)
        self.assertNotIn("fake/comment", imports)
        self.assertNotIn("fake/string", imports)

    def test_go_import_inventory_ignores_comments_and_string_literals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text(
                '''package main
// import "fake/comment"
import (
    "fmt"
    alias "example.com/real"
)
var text = "not/an/import"
func Run() {}
''',
                encoding="utf-8",
            )
            project = InventorySourceAdapter("go", (".go",)).analyze(root)
        self.assertEqual(set(project.units[0].dependencies), {"fmt", "example.com/real"})

    def test_traversal_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("print(1)", encoding="utf-8")
            (root / "b.py").write_text("print(2)", encoding="utf-8")
            adapter = InventorySourceAdapter("python", (".py",), max_scan_entries=1)
            with self.assertRaisesRegex(ValueError, "traversal exceeds configured limit"):
                adapter.analyze(root)

    def test_ignored_dependency_directories_do_not_consume_traversal_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("print(1)", encoding="utf-8")
            ignored = root / "node_modules" / "nested"
            ignored.mkdir(parents=True)
            (ignored / "vendor.py").write_text("print(2)", encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",), max_scan_entries=1).analyze(root)
            self.assertEqual([unit.relative_path for unit in project.units], ["main.py"])

    def test_total_size_limit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("1234", encoding="utf-8")
            (root / "b.py").write_text("5678", encoding="utf-8")
            adapter = InventorySourceAdapter("python", (".py",), max_file_bytes=100, max_total_bytes=6)
            with self.assertRaisesRegex(ValueError, "total size limit"):
                adapter.analyze(root)


if __name__ == "__main__":
    unittest.main()
