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
