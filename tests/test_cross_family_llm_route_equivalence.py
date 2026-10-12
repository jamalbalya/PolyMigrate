"""Cross-family LLM-route behavior fixtures for Go → JavaScript and JavaScript → C#.

A deterministic fixture provider supplies known target programs. These tests verify
pair routing, artifact paths, and source/target runtime comparison; they do not
validate live LLM translation quality.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class CrossFamilyFixtureProvider:
    provider_id = "fixture"
    model_id = "cross-family-fixture"

    def __init__(self, outputs):
        self.outputs = outputs
        self.requests = []

    def get_capabilities(self):
        return ProviderCapabilities()

    def generate(self, request: ModelRequest):
        self.requests.append(request)
        target = request.context["target_language"]
        return ModelResponse(json.dumps({
            "content": self.outputs[target],
            "assumptions": ["Fixed fixture output; not evidence of live-model quality."],
            "unsupported_features": [],
        }), self.provider_id, self.model_id)


class CrossFamilyLLMRouteEquivalenceTests(unittest.TestCase):
    def _migrate(self, root, source_language, target_language, source_text, target_text):
        extensions = {
            "go": (".go",), "javascript": (".js",), "csharp": (".cs",),
        }
        source = root / "source"
        source.mkdir()
        source_file = source / ("main" + extensions[source_language][0])
        source_file.write_text(source_text, encoding="utf-8")
        outputs = {target_language: target_text}
        provider = CrossFamilyFixtureProvider(outputs)
        providers = ProviderRegistry()
        providers.register(provider)
        registry = AdapterRegistry()
        registry.register_source(InventorySourceAdapter(source_language, extensions[source_language]))
        registry.register_target(LLMTargetAdapter(
            target_language, source_language, extensions[target_language][0],
            providers, "fixture", allow_source_upload=True,
            target_extensions=extensions[target_language],
        ))
        output = root / "generated"
        result = MigrationEngine(registry).execute(source, source_language, target_language, output)
        self.assertEqual(result.status, "GENERATED_UNVERIFIED")
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0].context["source_language"], source_language)
        self.assertEqual(provider.requests[0].context["target_language"], target_language)
        return source_file, output / ("main" + extensions[target_language][0])

    @unittest.skipUnless(shutil.which("go") and shutil.which("node"), "Go and Node.js are required")
    def test_go_to_javascript_fixture_preserves_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = self._migrate(
                root, "go", "javascript",
                'package main\nimport "fmt"\nfunc main() { fmt.Println(42) }\n',
                "console.log(42);\n",
            )
            env = dict(os.environ, GO111MODULE="off", GOTOOLCHAIN="local")
            original = subprocess.run(["go", "run", str(source)], capture_output=True, text=True, env=env, timeout=60)
            generated = subprocess.run(["node", str(target)], capture_output=True, text=True, timeout=30)
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)

    @unittest.skipUnless(shutil.which("node") and shutil.which("dotnet"), "Node.js and .NET SDK are required")
    def test_javascript_to_csharp_fixture_preserves_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, target = self._migrate(
                root, "javascript", "csharp",
                "console.log(42);\n",
                "using System;\nclass Program { static void Main() { Console.WriteLine(42); } }\n",
            )
            original = subprocess.run(["node", str(source)], capture_output=True, text=True, timeout=30)
            project = root / "generated"
            (project / "PolyMigrateFixture.csproj").write_text(
                '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
                '<TargetFramework>net8.0</TargetFramework><ImplicitUsings>disable</ImplicitUsings>'
                '<Nullable>enable</Nullable></PropertyGroup></Project>\n',
                encoding="utf-8",
            )
            build = subprocess.run(
                ["dotnet", "build", str(project / "PolyMigrateFixture.csproj"), "--nologo", "--verbosity", "quiet"],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            generated = subprocess.run(
                ["dotnet", str(project / "bin" / "Debug" / "net8.0" / "PolyMigrateFixture.dll")],
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(original.returncode, 0, original.stderr)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        self.assertEqual(original.stdout, generated.stdout)


if __name__ == "__main__":
    unittest.main()
