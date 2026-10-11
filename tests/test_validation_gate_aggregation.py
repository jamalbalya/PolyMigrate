"""Regression test for aggregate validation gate status."""
import tempfile
import unittest
from pathlib import Path
from polymigrate.validation.suite import validate_generated_project
from polymigrate.validation.runner import SandboxExecution

class FakeRunner:
    def __init__(self, statuses): self.statuses=iter(statuses)
    def run(self, workspace, image, command):
        status=next(self.statuses)
        return SandboxExecution(command.command_id,status,image,0 if status=="PASSED" else 1,0.01)

class ValidationGateAggregationTests(unittest.TestCase):
    def test_later_success_does_not_erase_earlier_build_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"first.cpp").write_text("int main() {}",encoding="utf-8")
            (root/"second.cpp").write_text("int main() {}",encoding="utf-8")
            result=validate_generated_project(root,"cpp","cpp:latest",FakeRunner(["FAILED","PASSED"]))
        self.assertEqual(result.gates["target_build"],"FAILED")
        self.assertEqual(len(result.executions),2)

if __name__ == "__main__": unittest.main()
