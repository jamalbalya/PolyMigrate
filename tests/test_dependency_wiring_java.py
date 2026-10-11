"""Java import/manifest consistency tests; mapping ambiguity must not be promoted."""
import tempfile
import unittest
from pathlib import Path

from polymigrate.validation.dependency_wiring import review_dependency_wiring


class JavaDependencyWiringTests(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        root = Path(tmp) / "project"
        root.mkdir()
        return root

    def test_jdk_imports_need_no_external_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "Main.java").write_text(
                "import java.util.List;\npublic class Main { List<String> items; }\n",
                encoding="utf-8",
            )
            result = review_dependency_wiring(root, "java")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.observed_imports, ("java.util.List",))
        self.assertEqual(result.declared_dependencies, ())

    def test_local_package_import_is_not_reported_as_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "Main.java").write_text(
                "package com.example.app;\nimport com.example.app.Helper;\nclass Main {}\n",
                encoding="utf-8",
            )
            (root / "Helper.java").write_text(
                "package com.example.app;\nclass Helper {}\n", encoding="utf-8"
            )
            result = review_dependency_wiring(root, "java")
        self.assertEqual(result.status, "PASSED")
        self.assertEqual(result.missing_declarations, ())

    def test_external_import_without_manifest_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "Main.java").write_text(
                "import com.vendor.Widget;\nclass Main { Widget item; }\n",
                encoding="utf-8",
            )
            result = review_dependency_wiring(root, "java")
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.missing_declarations, ("com.vendor.Widget",))

    def test_maven_coordinate_is_recorded_but_import_mapping_stays_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "Main.java").write_text(
                "import com.vendor.Widget;\nclass Main { Widget item; }\n",
                encoding="utf-8",
            )
            (root / "pom.xml").write_text(
                "<project><dependencies><dependency><groupId>com.vendor</groupId>"
                "<artifactId>widget-sdk</artifactId><version>1.0</version>"
                "</dependency></dependencies></project>",
                encoding="utf-8",
            )
            result = review_dependency_wiring(root, "java")
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.declared_dependencies, ("com.vendor:widget-sdk",))
        self.assertTrue(any("mapping is ambiguous" in warning for warning in result.warnings))

    def test_gradle_coordinate_is_recorded_but_import_mapping_stays_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "Main.java").write_text(
                "import org.example.api.Client;\nclass Main { Client client; }\n",
                encoding="utf-8",
            )
            (root / "build.gradle.kts").write_text(
                'dependencies { implementation("org.example:client-sdk:1.2.3") }\n',
                encoding="utf-8",
            )
            result = review_dependency_wiring(root, "java")
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.declared_dependencies, ("org.example:client-sdk",))

    def test_malformed_maven_manifest_is_not_treated_as_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "Main.java").write_text(
                "import com.vendor.Widget;\nclass Main { Widget item; }\n",
                encoding="utf-8",
            )
            (root / "pom.xml").write_text("<project><dependencies>", encoding="utf-8")
            result = review_dependency_wiring(root, "java")
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertTrue(any("could not be parsed" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
