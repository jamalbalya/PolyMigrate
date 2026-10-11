"""Java import/manifest consistency tests; mapping ambiguity must not be promoted."""
import tempfile
import zipfile
import unittest
from pathlib import Path

from polymigrate.validation.dependency_wiring import java_candidate_jar_imports, review_dependency_wiring


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

    def test_wildcard_external_import_is_inventory_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            (root / "Main.java").write_text(
                "import com.vendor.widgets.*;\nclass Main {}\n", encoding="utf-8"
            )
            result = review_dependency_wiring(root, "java")
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.observed_imports, ("com.vendor.widgets",))
        self.assertEqual(result.missing_declarations, ("com.vendor.widgets",))

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

    def test_declared_jar_class_import_must_be_used_not_merely_imported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lib").mkdir()
            jar_path = root / "lib" / "widget-sdk.jar"
            with zipfile.ZipFile(jar_path, "w") as archive:
                archive.writestr("com/vendor/Widget.class", b"class-name-fixture")
            (root / "pom.xml").write_text(
                "<project><dependencies><dependency><groupId>com.vendor</groupId>"
                "<artifactId>widget-sdk</artifactId><version>1.0</version><scope>system</scope>"
                "<systemPath>$" "{project.basedir}/lib/widget-sdk.jar</systemPath>"
                "</dependency></dependencies></project>",
                encoding="utf-8",
            )
            (root / "Main.java").write_text(
                "import com.vendor.Widget;\nclass Main {}\n", encoding="utf-8"
            )
            self.assertEqual(
                java_candidate_jar_imports(root, "com.vendor:widget-sdk", {"com.vendor.Widget"}),
                set(),
            )
            (root / "Main.java").write_text(
                "import com.vendor.Widget;\nclass Main { Widget value; }\n", encoding="utf-8"
            )
            self.assertEqual(
                java_candidate_jar_imports(root, "com.vendor:widget-sdk", {"com.vendor.Widget"}),
                {"com.vendor.Widget"},
            )

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
