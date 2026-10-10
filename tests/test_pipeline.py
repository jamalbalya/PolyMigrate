"""Migration adapter pipeline tests."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from polymigrate.migration.pipeline import (
    AdapterRegistry, GeneratedArtifact, MigrationEngine, SourceProject, SourceUnit,
)


class PythonSourceAdapter:
    language_id = "python"
    def __init__(self, text="print('hello')", path="main.py", invalid_hash=False):
        self.text, self.path, self.invalid_hash = text, path, invalid_hash
    def analyze(self, source_root):
        digest = "invalid" if self.invalid_hash else hashlib.sha256(self.text.encode()).hexdigest()
        return SourceProject(source_root, "python", (SourceUnit(self.path, self.text, digest),))


class GoTargetAdapter:
    language_id = "go"
    def __init__(self, artifacts=None):
        self.artifacts = artifacts if artifacts is not None else [GeneratedArtifact("main.go", "package main\n")]
    def generate(self, project, context):
        return self.artifacts


def engine_with(target=None, source=None):
    registry = AdapterRegistry()
    registry.register_source(source or PythonSourceAdapter())
    registry.register_target(target or GoTargetAdapter())
    return MigrationEngine(registry)


class MigrationPipelineTests(unittest.TestCase):
    def test_writes_generated_files_outside_source_and_marks_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            (root / "main.py").write_text("print('hello')", encoding="utf-8")
            output = Path(tmp) / "output"
            result = engine_with().execute(root, "python", "go", output)
            self.assertEqual(result.status, "GENERATED_UNVERIFIED")
            self.assertEqual(result.generated_files, ("main.go",))
            self.assertTrue((output / "main.go").read_text(encoding="utf-8").startswith("package main"))
            self.assertEqual((root / "main.py").read_text(encoding="utf-8"), "print('hello')")
            self.assertTrue(result.warnings)

    def test_rejects_output_inside_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "outside the source"):
                engine_with().execute(root, "python", "go", root / "out")

    def test_rejects_path_traversal_from_target_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            target = GoTargetAdapter([GeneratedArtifact("../escape.go", "package main")])
            with self.assertRaisesRegex(ValueError, "unsafe output path"):
                engine_with(target).execute(root, "python", "go", Path(tmp) / "out")
            self.assertFalse((Path(tmp) / "escape.go").exists())

    def test_rejects_invalid_source_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            with self.assertRaisesRegex(ValueError, "invalid content hash"):
                engine_with(source=PythonSourceAdapter(invalid_hash=True)).execute(
                    root, "python", "go", Path(tmp) / "out")

    def test_rejects_existing_nonempty_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            output = Path(tmp) / "out"
            output.mkdir()
            (output / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "absent or empty"):
                engine_with().execute(root, "python", "go", output)
            self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_rejects_output_file_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            target = GoTargetAdapter([GeneratedArtifact(f"{i}.go", "package main") for i in range(3)])
            registry = AdapterRegistry()
            registry.register_source(PythonSourceAdapter())
            registry.register_target(target)
            engine = MigrationEngine(registry, max_generated_files=2)
            with self.assertRaisesRegex(ValueError, "file limit"):
                engine.execute(root, "python", "go", Path(tmp) / "out")


if __name__ == "__main__":
    unittest.main()
