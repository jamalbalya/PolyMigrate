"""Resource-limit tests for source inventory."""
import tempfile
import unittest
from pathlib import Path
from polymigrate.migration.adapters import InventorySourceAdapter


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
            (root / "broken.py").write_text("def broken(:\\n", encoding="utf-8")
            project = InventorySourceAdapter("python", (".py",)).analyze(root)
            self.assertEqual(len(project.units), 1)
            self.assertEqual(project.units[0].symbols, ())
            self.assertTrue(any("could not be parsed safely" in warning for warning in project.metadata["warnings"]))

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
