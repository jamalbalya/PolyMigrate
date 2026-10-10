"""Behavior comparison is tested with a fake runner; production commands remain Docker-isolated."""
import json
import tempfile
import unittest
from pathlib import Path

from polymigrate.validation.behavior import compare_behavior
from polymigrate.validation.runner import SandboxExecution


class FakeBehaviorRunner:
    def __init__(self, target_stdout="42\n", source_stdout="42\n", status="PASSED"):
        self.target_stdout = target_stdout
        self.source_stdout = source_stdout
        self.status = status
        self.calls = []

    def run(self, workspace, image, command):
        self.calls.append((workspace, image, command))
        self.assert_snapshot = (workspace / ("main.py" if "source" in command.command_id else "main.go")).is_file()
        (workspace / "runner-mutation.txt").write_text("isolated", encoding="utf-8")
        output = self.source_stdout if "source" in command.command_id else self.target_stdout
        return SandboxExecution(
            command.command_id, self.status, image, 0 if self.status == "PASSED" else 1,
            0.01, output, "", "fixture execution",
        )


class BehaviorComparisonTests(unittest.TestCase):
    def _fixture(self, root: Path):
        source = root / "source"
        target = root / "target"
        source.mkdir()
        target.mkdir()
        (source / "main.py").write_text("print(42)\n", encoding="utf-8")
        (target / "main.go").write_text('package main\nfunc main() {}\n', encoding="utf-8")
        spec = root / "behavior.json"
        spec.write_text(json.dumps({
            "source_command": ["python", "main.py"],
            "target_command": ["go", "run", "main.go"],
            "cases": [{"name": "answer", "expected_stdout": "42\n"}],
        }), encoding="utf-8")
        return source, target, spec

    def test_compares_source_and_target_output_in_isolated_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, spec = self._fixture(Path(tmp))
            runner = FakeBehaviorRunner()
            result = compare_behavior(spec, source, target, "python:3.12-slim", "golang:1.23", runner)
            self.assertEqual(result.status, "PASSED")
            self.assertEqual(result.cases_checked, 1)
            self.assertEqual(len(runner.calls), 2)
            self.assertFalse((source / "runner-mutation.txt").exists())
            self.assertFalse((target / "runner-mutation.txt").exists())
            self.assertTrue(any("not a proof" in warning for warning in result.warnings))

    def test_mismatched_target_output_fails_behavior_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, spec = self._fixture(Path(tmp))
            result = compare_behavior(
                spec, source, target, "python:3.12-slim", "golang:1.23",
                FakeBehaviorRunner(target_stdout="41\n"),
            )
            self.assertEqual(result.status, "FAILED")
            self.assertTrue(any("target behavior" in warning for warning in result.warnings))

    def test_shell_and_parent_traversal_commands_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, spec = self._fixture(Path(tmp))
            payload = json.loads(spec.read_text(encoding="utf-8"))
            payload["source_command"] = ["sh", "-c", "python main.py"]
            spec.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "non-allowlisted executable"):
                compare_behavior(spec, source, target, "python:3.12-slim", "golang:1.23", FakeBehaviorRunner())

    def test_missing_images_block_comparison_without_running_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, spec = self._fixture(Path(tmp))
            runner = FakeBehaviorRunner()
            result = compare_behavior(spec, source, target, None, "golang:1.23", runner)
            self.assertEqual(result.status, "BLOCKED")
            self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
