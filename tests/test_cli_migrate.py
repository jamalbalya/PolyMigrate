"""End-to-end CLI tests for experimental migration with a deterministic fake model."""
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


class FakeTranslationProvider:
    provider_id = "fake"
    def get_capabilities(self):
        return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        return ModelResponse(json.dumps({
            "content": "package main\nfunc main() {}\n",
            "assumptions": [],
            "unsupported_features": [],
        }), "fake", "fake-model")


class MigrateCLIE2ETests(unittest.TestCase):
    def setUp(self):
        self.registry = ProviderRegistry()
        self.registry.register(FakeTranslationProvider())

    def test_migrate_writes_output_and_unverified_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            source_file = source / "main.py"
            source_file.write_text("print('hello')", encoding="utf-8")
            output = Path(tmp) / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry", return_value=(self.registry, ())), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["migrate", "--source", str(source), "--from", "python", "--to", "go",
                             "--output", str(output), "--provider", "fake", "--allow-source-upload"])
            self.assertEqual(code, 0, stderr.getvalue())
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "GENERATED_UNVERIFIED")
            self.assertEqual(report["validation_gates"]["target_build"], "NOT_RUN")
            self.assertTrue((output / "main.go").is_file())
            self.assertEqual(source_file.read_text(encoding="utf-8"), "print('hello')")

    def test_migrate_requires_source_upload_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print('hello')", encoding="utf-8")
            output = Path(tmp) / "out"
            stderr = StringIO()
            with patch("polymigrate.cli.build_provider_registry", return_value=(self.registry, ())), redirect_stderr(stderr):
                code = main(["migrate", "--source", str(source), "--from", "python", "--to", "go",
                             "--output", str(output), "--provider", "fake"])
            self.assertEqual(code, 2)
            self.assertIn("Source upload is disabled", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
