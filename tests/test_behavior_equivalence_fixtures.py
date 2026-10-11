"""Trusted arithmetic fixtures exercise real behavior comparison for Python <-> Go."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine


class ArithmeticFixtureProvider:
    provider_id = "fixture"
    model_id = "fixture-model"

    def get_capabilities(self):
        return ProviderCapabilities()

    def generate(self, request: ModelRequest):
        target = request.context["target_language"]
        content = {
            "go": 'package main\nimport "fmt"\nfunc main() { fmt.Println(7 * 6) }\n',
            "python": "print(7 * 6)\n",
        }[target]
        return ModelResponse(json.dumps({
            "content": content, "assumptions": [], "unsupported_features": [],
        }), self.provider_id, self.model_id)


@unittest.skipUnless(shutil.which("go"), "Go toolchain is required for behavior-equivalence fixtures")
class BehaviorEquivalenceFixtureTests(unittest.TestCase):
    def _migrate(self, root: Path, source_language: str, target_language: str, source_text: str):
        source = root / "source"
        source.mkdir()
        source_path = source / ("main.py" if source_language == "python" else "main.go")
        source_path.write_text(source_text, encoding="utf-8")
        output = root / "generated"
        provider = ArithmeticFixtureProvider()
        providers = ProviderRegistry()
        providers.register(provider)
        adapters = AdapterRegistry()
        extensions = {"python": (".py",), "go": (".go",)}
        adapters.register_source(InventorySourceAdapter(source_language, extensions[source_language]))
        adapters.register_target(LLMTargetAdapter(
            target_language, source_language, extensions[target_language][0],
            providers, "fixture", allow_source_upload=True,
            target_extensions=extensions[target_language],
        ))
        result = MigrationEngine(adapters).execute(source, source_language, target_language, output)
        self.assertEqual(result.status, "GENERATED_UNVERIFIED")
        return source_path, output / ("main.py" if target_language == "python" else "main.go")

    def _run(self, language: str, path: Path) -> str:
        if language == "python":
            command = [sys.executable, str(path)]
            env = None
        else:
            command = ["go", "run", str(path)]
            import os
            env = dict(os.environ, GO111MODULE="off", GOTOOLCHAIN="local")
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_python_to_go_preserves_fixture_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, generated = self._migrate(
                Path(tmp), "python", "go", "print(7 * 6)\n",
            )
            self.assertEqual(self._run("python", source), self._run("go", generated))

    def test_go_to_python_preserves_fixture_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, generated = self._migrate(
                Path(tmp), "go", "python",
                'package main\nimport "fmt"\nfunc main() { fmt.Println(7 * 6) }\n',
            )
            self.assertEqual(self._run("go", source), self._run("python", generated))


if __name__ == "__main__":
    unittest.main()
