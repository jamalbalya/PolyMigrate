"""Real Docker smoke test for the behavior comparator; enabled only in its dedicated CI job."""
import json
import os
import tempfile
import unittest
from pathlib import Path

from polymigrate.validation.behavior import compare_behavior


@unittest.skipUnless(os.environ.get("POLYMIGRATE_RUN_DOCKER_E2E") == "1", "requires pre-pulled Docker test images")
class DockerBehaviorComparisonTests(unittest.TestCase):
    def test_python_to_go_behavior_matches_expected_output_in_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            (target / "main.go").write_text(
                'package main\nimport "fmt"\nfunc main() { fmt.Println(42) }\n',
                encoding="utf-8",
            )
            spec = root / "behavior.json"
            spec.write_text(json.dumps({
                "source_command": ["python", "main.py"],
                "target_command": ["go", "run", "main.go"],
                "cases": [{"name": "basic", "expected_stdout": "42\n", "timeout_seconds": 60}],
            }), encoding="utf-8")
            result = compare_behavior(
                spec, source, target, "python:3.12-slim", "golang:1.23-alpine",
            )
            self.assertEqual(result.status, "PASSED", json.dumps(result.to_dict(), indent=2))
            self.assertEqual(result.cases_checked, 1)
            self.assertEqual(len(result.executions), 2)

    def test_python_to_node_behavior_matches_expected_output_in_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            (target / "main.js").write_text("console.log(42);\n", encoding="utf-8")
            spec = root / "behavior.json"
            spec.write_text(json.dumps({
                "source_command": ["python", "main.py"],
                "target_command": ["node", "main.js"],
                "cases": [{"name": "basic", "expected_stdout": "42\n"}],
            }), encoding="utf-8")
            result = compare_behavior(
                spec, source, target, "python:3.12-slim", "node:22-alpine",
            )
            self.assertEqual(result.status, "PASSED", json.dumps(result.to_dict(), indent=2))
            self.assertEqual(result.cases_checked, 1)
            self.assertEqual(len(result.executions), 2)


if __name__ == "__main__":
    unittest.main()
