"""Constrained manifest reconstruction tests use a deterministic provider."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.cli import main
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.manifest_reconstruction import reconstruct_target_manifests
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class ManifestFixtureProvider:
    provider_id = "fixture"
    model_id = "fixture-model"

    def __init__(self, manifest_payload=None):
        self.requests = []
        self.manifest_payload = manifest_payload or {
            "files": [{"path": "go.mod", "content": "module example.invalid/migrated\\n\\ngo 1.23\\n"}],
            "warnings": [],
        }

    def get_capabilities(self):
        return ProviderCapabilities()

    def generate(self, request: ModelRequest):
        self.requests.append(request)
        if request.task == "reconstruct_target_manifests":
            payload = self.manifest_payload
        else:
            payload = {"content": "package main\\nfunc main() {}\\n", "assumptions": [], "unsupported_features": []}
        return ModelResponse(json.dumps(payload), self.provider_id, self.model_id)


class ManifestReconstructionTests(unittest.TestCase):
    def test_manifest_is_generated_as_unverified_artifact_with_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("print(1)\\n", encoding="utf-8")
            providers = ProviderRegistry()
            provider = ManifestFixtureProvider()
            providers.register(provider)
            adapters = AdapterRegistry()
            adapters.register_source(InventorySourceAdapter("python", (".py",)))
            adapters.register_target(LLMTargetAdapter(
                "go", "python", ".go", providers, "fixture",
                allow_source_upload=True, target_extensions=(".go",),
            ))
            result = MigrationEngine(adapters).execute(source, "python", "go", root / "out", {
                "reconstruct_manifests": True,
                "source_manifests": [{"path": "pyproject.toml", "content": "[project]\\nname='demo'\\n"}],
                "dependency_inventory": [],
                "library_resolution": [],
            })
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertTrue((root / "out" / "main.go").is_file())
            self.assertEqual((root / "out" / "go.mod").read_text(encoding="utf-8"), "module example.invalid/migrated\\n\\ngo 1.23\\n")
            self.assertEqual([request.task for request in provider.requests],
                             ["translate_source_file", "reconstruct_target_manifests"])

    def test_cli_reconstructs_target_manifest_when_source_manifest_exists(self):
        providers = ProviderRegistry()
        provider = ManifestFixtureProvider()
        providers.register(provider)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("print(1)\\n", encoding="utf-8")
            (source / "pyproject.toml").write_text("[project]\\nname='demo'\\n", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry", return_value=(providers, ())), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python", "--to", "go",
                    "--output", str(output), "--provider", "fixture", "--allow-source-upload",
                ])
            self.assertEqual(code, 3, stderr.getvalue())
            self.assertTrue((output / "main.go").is_file())
            self.assertTrue((output / "go.mod").is_file())
            review = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertIn("unverified", json.dumps(review).lower())
            self.assertIn("parser_backends", review["source_inventory"])
            self.assertEqual([request.task for request in provider.requests],
                             ["translate_source_file", "reconstruct_target_manifests"])

    def test_rejects_unapproved_paths_and_executable_package_scripts(self):
        providers = ProviderRegistry()
        provider = ManifestFixtureProvider({
            "files": [
                {"path": "../../escape.go", "content": "module bad"},
                {"path": "package.json", "content": '{"name":"demo","scripts":{"test":"node test.js"}}'},
            ],
            "warnings": [],
        })
        providers.register(provider)
        artifacts, warnings = reconstruct_target_manifests(
            "javascript", [{"path": "package.json", "content": '{"name":"source"}'}],
            [], [], providers, "fixture",
        )
        self.assertEqual(artifacts, [])
        self.assertTrue(any("unapproved" in warning for warning in warnings))
        self.assertTrue(any("package.json" in warning for warning in warnings))

    def test_rejects_pyproject_build_system_and_cargo_build_dependencies(self):
        cases = (
            (
                "python", "pyproject.toml",
                '[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n',
                "build-system section",
            ),
            (
                "rust", "Cargo.toml",
                '[package]\nname = "demo"\nversion = "0.1.0"\n\n[build-dependencies]\ncc = "1"\n',
                "build script or build dependencies",
            ),
            (
                "rust", "Cargo.toml",
                '[package]\nname = "demo"\nversion = "0.1.0"\n\n[target.\'cfg(unix)\'.build-dependencies]\ncc = "1"\n',
                "build script or build dependencies",
            ),
        )
        for target, path, content, warning_text in cases:
            provider = ManifestFixtureProvider({
                "files": [{"path": path, "content": content}],
                "warnings": [],
            })
            providers = ProviderRegistry()
            providers.register(provider)
            with self.subTest(path=path):
                artifacts, warnings = reconstruct_target_manifests(
                    target, [{"path": "source-manifest", "content": "fixture"}],
                    [], [], providers, "fixture",
                )
                self.assertEqual(artifacts, [])
                self.assertTrue(any(warning_text in warning for warning in warnings), warnings)

    def test_rejects_executable_gradle_build_scripts(self):
        malicious = (
            'plugins { id("org.example.untrusted") version "1.0" }',
            'tasks.register("exfiltrate") { doLast { println("run") } }',
            'apply(from = "untrusted.gradle.kts")',
            'buildscript { repositories { mavenCentral() } }',
            'dependencies { implementation("$payload") }',
        )
        for body in malicious:
            provider = ManifestFixtureProvider({
                "files": [{"path": "build.gradle.kts", "content": body}],
                "warnings": [],
            })
            providers = ProviderRegistry()
            providers.register(provider)
            with self.subTest(body=body):
                artifacts, warnings = reconstruct_target_manifests(
                    "kotlin", [{"path": "source-manifest", "content": "fixture"}],
                    [], [], providers, "fixture",
                )
                self.assertEqual(artifacts, [])
                self.assertTrue(any("non-declarative Gradle manifest" in warning for warning in warnings), warnings)

    def test_accepts_only_restricted_static_gradle_dsl(self):
        settings = "\n".join(['rootProject.name = "demo"', ""])
        build = "\n".join([
            "repositories {", "    mavenCentral()", "}",
            "dependencies {", '    implementation("org.example:lib:1.0")', "}", "",
        ])
        provider = ManifestFixtureProvider({
            "files": [
                {"path": "settings.gradle.kts", "content": settings},
                {"path": "build.gradle.kts", "content": build},
            ],
            "warnings": [],
        })
        providers = ProviderRegistry()
        providers.register(provider)
        artifacts, warnings = reconstruct_target_manifests(
            "kotlin", [{"path": "source-manifest", "content": "fixture"}],
            [], [], providers, "fixture",
        )
        self.assertEqual({item.relative_path for item in artifacts}, {"settings.gradle.kts", "build.gradle.kts"})
        self.assertTrue(any("unverified" in warning.lower() for warning in warnings))

    def test_rejects_recognizable_secrets_in_manifest_content(self):
        providers = ProviderRegistry()
        provider = ManifestFixtureProvider({
            "files": [{"path": "go.mod", "content": "module x\\n// API_KEY = \"sk-12345678901234567890\"\\n"}],
            "warnings": [],
        })
        providers.register(provider)
        artifacts, warnings = reconstruct_target_manifests(
            "go", [{"path": "go.mod", "content": "module source"}], [], [], providers, "fixture",
        )
        self.assertEqual(artifacts, [])
        self.assertTrue(any("secret material" in warning for warning in warnings))


    def test_rejects_executable_swift_package_manifests(self):
        malicious = (
            'import Foundation\\ntry! Process()',
            'import PackageDescription\\nlet payload = try! String(contentsOfFile: "/etc/passwd")\\nlet package = Package(name: "demo")',
            'import PackageDescription\\nlet package = Package(name: "demo", targets: [])\\n// extra\\ntry! FileManager.default.removeItem(atPath: "/tmp/x")',
        )
        for body in malicious:
            provider = ManifestFixtureProvider({
                "files": [{"path": "Package.swift", "content": body}],
                "warnings": [],
            })
            providers = ProviderRegistry()
            providers.register(provider)
            with self.subTest(body=body):
                artifacts, warnings = reconstruct_target_manifests(
                    "swift", [{"path": "source-manifest", "content": "fixture"}],
                    [], [], providers, "fixture",
                )
                self.assertEqual(artifacts, [])
                self.assertTrue(any("non-declarative Package.swift" in warning for warning in warnings), warnings)

    def test_accepts_only_restricted_static_swift_package_manifest(self):
        body = "\\n".join([
            "// swift-tools-version: 5.9",
            "import PackageDescription",
            "let package = Package(",
            '    name: "demo",',
            "    products: [",
            '        .executable(name: "demo", targets: ["demo"]),',
            "    ],",
            "    targets: [",
            '        .executableTarget(name: "demo"),',
            "    ],",
            ")",
            "",
        ])
        provider = ManifestFixtureProvider({
            "files": [{"path": "Package.swift", "content": body}],
            "warnings": [],
        })
        providers = ProviderRegistry()
        providers.register(provider)
        artifacts, warnings = reconstruct_target_manifests(
            "swift", [{"path": "source-manifest", "content": "fixture"}],
            [], [], providers, "fixture",
        )
        self.assertEqual([item.relative_path for item in artifacts], ["Package.swift"])
        self.assertTrue(any("unverified" in warning.lower() for warning in warnings))

    def test_rejects_maven_xml_external_entities(self):
        malicious = (
            '<!DOCTYPE project [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><project><modelVersion>4.0.0</modelVersion>&xxe;</project>',
            '<!ENTITY leak SYSTEM "https://example.invalid/leak"><project/>',
            '<project><description>SYSTEM "file:///etc/passwd"</description></project>',
        )
        for body in malicious:
            provider = ManifestFixtureProvider({
                "files": [{"path": "pom.xml", "content": body}],
                "warnings": [],
            })
            providers = ProviderRegistry()
            providers.register(provider)
            with self.subTest(body=body):
                artifacts, warnings = reconstruct_target_manifests(
                    "java", [{"path": "source-manifest", "content": "fixture"}],
                    [], [], providers, "fixture",
                )
                self.assertEqual(artifacts, [])
                self.assertTrue(any("DTD, entity declaration, or external XML identifier" in warning for warning in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
