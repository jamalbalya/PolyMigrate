"""Static target dependency wiring checks."""
import tempfile
import unittest
from pathlib import Path

from polymigrate.validation.dependency_wiring import review_dependency_wiring


class DependencyWiringReviewTests(unittest.TestCase):
    def test_go_external_import_without_go_mod_declaration_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text(
                'package main\nimport "github.com/example/library"\nfunc main() {}\n',
                encoding="utf-8",
            )
            result = review_dependency_wiring(root, "go")
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("github.com/example/library", result.missing_declarations)

    def test_go_external_import_with_go_mod_declaration_passes_static_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text(
                'package main\nimport "github.com/example/library"\nfunc main() {}\n',
                encoding="utf-8",
            )
            (root / "go.mod").write_text(
                "module example.com/app\n\ngo 1.23\nrequire github.com/example/library v1.2.3\n",
                encoding="utf-8",
            )
            result = review_dependency_wiring(root, "go")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.missing_declarations, ())
        self.assertTrue(result.to_dict()["does_not_prove_build_or_api_compatibility"])

    def test_javascript_external_import_without_package_declaration_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.js").write_text(
                'import leftPad from "left-pad";\nconsole.log(leftPad("x", 2));\n',
                encoding="utf-8",
            )
            (root / "package.json").write_text('{"name":"fixture"}', encoding="utf-8")
            result = review_dependency_wiring(root, "javascript")
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("left-pad", result.missing_declarations)

    def test_python_standard_library_import_needs_no_dependency_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("import json\nimport pathlib\n", encoding="utf-8")
            result = review_dependency_wiring(root, "python")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.missing_declarations, ())

    def test_unsupported_language_is_explicitly_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = review_dependency_wiring(Path(tmp), "java")
        self.assertEqual(result.status, "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
