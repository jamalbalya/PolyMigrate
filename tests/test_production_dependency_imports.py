"""Dependency candidate proof must observe production imports, not test-only imports."""
import tempfile
import unittest
from pathlib import Path

from polymigrate.validation.dependency_wiring import review_dependency_wiring


class ProductionDependencyImportTests(unittest.TestCase):
    def test_test_only_import_does_not_count_as_production_dependency_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text("import requests\n", encoding="utf-8")
            (root / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
            result = review_dependency_wiring(root, "python")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.observed_imports, ())

    def test_production_import_is_reported_for_candidate_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("import requests\n", encoding="utf-8")
            (root / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
            result = review_dependency_wiring(root, "python")
        self.assertEqual(result.observed_imports, ("requests",))


if __name__ == "__main__":
    unittest.main()
