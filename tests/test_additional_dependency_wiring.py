"""Dependency wiring checks stay conservative for Kotlin, Ruby, and PHP."""
import json
import tempfile
import unittest
from pathlib import Path

from polymigrate.validation.dependency_wiring import review_dependency_wiring


class AdditionalDependencyWiringTests(unittest.TestCase):
    def test_kotlin_external_import_without_build_manifest_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Main.kt").write_text("import org.example.library.Client\nfun main() {}\n", encoding="utf-8")
            result = review_dependency_wiring(root, "kotlin")
        self.assertEqual(result.status, "BLOCKED")
        self.assertTrue(any("Missing Kotlin dependency manifest" in item for item in result.warnings))

    def test_kotlin_external_import_with_manifest_remains_unverified_until_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Main.kt").write_text("import org.example.library.Client\nfun main() {}\n", encoding="utf-8")
            (root / "build.gradle.kts").write_text('dependencies { implementation("org.example:library:1.0") }\n', encoding="utf-8")
            result = review_dependency_wiring(root, "kotlin")
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertTrue(result.to_dict()["does_not_prove_build_or_api_compatibility"])

    def test_ruby_stdlib_import_needs_no_gemfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rb").write_text("require 'json'\nputs JSON.generate({ok: true})\n", encoding="utf-8")
            result = review_dependency_wiring(root, "ruby")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.missing_declarations, ())

    def test_ruby_external_require_without_gemfile_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rb").write_text("require 'nokogiri'\n", encoding="utf-8")
            result = review_dependency_wiring(root, "ruby")
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("nokogiri", result.missing_declarations)

    def test_ruby_gemfile_match_is_static_pass_not_build_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rb").write_text("require 'nokogiri'\n", encoding="utf-8")
            (root / "Gemfile").write_text("gem 'nokogiri', '~> 1.16'\n", encoding="utf-8")
            result = review_dependency_wiring(root, "ruby")
        self.assertEqual(result.status, "PASSED")
        self.assertTrue(result.to_dict()["does_not_prove_build_or_api_compatibility"])

    def test_php_missing_composer_manifest_is_blocked_for_namespace_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.php").write_text("<?php\nuse Vendor\\Package\\Client;\n", encoding="utf-8")
            result = review_dependency_wiring(root, "php")
        self.assertEqual(result.status, "BLOCKED")
        self.assertTrue(any("Missing composer.json" in item for item in result.warnings))

    def test_php_local_psr4_namespace_is_not_treated_as_external_dependency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.php").write_text("<?php\nuse App\\Service\\Client;\n", encoding="utf-8")
            (root / "composer.json").write_text(json.dumps({
                "autoload": {"psr-4": {"App\\\\": "src/"}},
                "require": {},
            }), encoding="utf-8")
            result = review_dependency_wiring(root, "php")
        self.assertEqual(result.status, "PASSED")

    def test_php_external_namespace_with_manifest_remains_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.php").write_text("<?php\nuse Vendor\\Package\\Client;\n", encoding="utf-8")
            (root / "composer.json").write_text(json.dumps({"require": {"vendor/package": "^1.0"}}), encoding="utf-8")
            result = review_dependency_wiring(root, "php")
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertTrue(any("mapping is ambiguous" in item for item in result.warnings))


if __name__ == "__main__":
    unittest.main()
