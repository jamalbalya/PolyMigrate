"""Regression test ensuring invalid later artifacts cannot leave partial output."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from polymigrate.migration.pipeline import (
    AdapterRegistry, GeneratedArtifact, MigrationEngine, SourceProject, SourceUnit,
)


class Source:
    language_id = "python"
    def analyze(self, root):
        text = "print('source')"
        return SourceProject(root, "python", (
            SourceUnit("main.py", text, hashlib.sha256(text.encode()).hexdigest()),
        ))


class Target:
    language_id = "go"
    def generate(self, project, context):
        return [GeneratedArtifact("main.go", "package main"), GeneratedArtifact("../escape.go", "bad")]


class PipelineRegressionTests(unittest.TestCase):
    def test_bad_second_artifact_does_not_write_first_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            output = Path(tmp) / "output"
            registry = AdapterRegistry()
            registry.register_source(Source())
            registry.register_target(Target())
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                MigrationEngine(registry).execute(root, "python", "go", output)
            self.assertFalse((output / "main.go").exists())
            self.assertFalse((Path(tmp) / "escape.go").exists())


if __name__ == "__main__":
    unittest.main()
