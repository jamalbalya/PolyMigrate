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
