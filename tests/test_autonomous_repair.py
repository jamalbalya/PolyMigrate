"""Autonomous repair loop tests use fake providers and validation results."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.validation.repair import AutonomousRepairLoop
from polymigrate.validation.runner import SandboxExecution
from polymigrate.validation.suite import ValidationSuiteResult


class FakeProvider:
    provider_id="fake"
    def __init__(self,payload): self.payload=payload; self.requests=[]
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self,request:ModelRequest):
        self.requests.append(request)
        return ModelResponse(json.dumps(self.payload),"fake","test-model")


def validation(status, command_status=None, stderr=""):
    gates={"target_build":status,"unit_tests":"NOT_RUN","integration_tests":"NOT_RUN",
           "e2e_tests":"NOT_RUN","behavior_comparison":"NOT_RUN","security_review":"NOT_RUN"}
    executions=()
    if command_status:
        executions=(SandboxExecution(command_id="build-go",status=command_status,image="golang:test",
                                     exit_code=0 if command_status=="PASSED" else 1,
                                     duration_seconds=0.1,stderr=stderr),)
    return ValidationSuiteResult(gates,executions,())


class AutonomousRepairTests(unittest.TestCase):
    def test_failed_build_is_repaired_and_retested(self):
        provider=FakeProvider({"files":[{"path":"main.go","content":"package main\nfunc main() {}\n"}],
                               "rationale":"Corrected malformed syntax.","assumptions":[]})
        providers=ProviderRegistry()
        providers.register(provider)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"main.go").write_text("package main\nfunc main( {\n",encoding="utf-8")
            with patch("polymigrate.validation.repair.validate_generated_project",
                       return_value=validation("PASSED","PASSED")) as validate_project:
                result=AutonomousRepairLoop(providers,"fake","go",(".go",),max_attempts=2).run(
                    root,"golang:test",{"library_resolution":[]},initial_validation=validation("FAILED","FAILED","main.go: syntax error"))
            self.assertEqual((root/"main.go").read_text(encoding="utf-8"),"package main\nfunc main() {}\n")
        self.assertEqual(result.status,"REPAIRED_AND_RETESTED")
        self.assertEqual(result.attempts[0].status,"APPLIED")
        self.assertEqual(validate_project.call_count,1)
        self.assertIn("validation_failures",provider.requests[0].prompt)

    def test_path_traversal_repair_is_rejected(self):
        provider=FakeProvider({"files":[{"path":"../outside.go","content":"package main"}],"rationale":"bad path"})
        providers=ProviderRegistry()
        providers.register(provider)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"main.go").write_text("package main\n",encoding="utf-8")
            result=AutonomousRepairLoop(providers,"fake","go",(".go",)).run(
                root,"golang:test",initial_validation=validation("FAILED","FAILED","main.go: error"))
            self.assertEqual((root/"main.go").read_text(encoding="utf-8"),"package main\n")
        self.assertEqual(result.status,"UNRESOLVED")
        self.assertEqual(result.attempts[0].status,"FAILED")

    def test_blocked_validation_does_not_spend_ai_calls_on_repairs(self):
        provider=FakeProvider({})
        providers=ProviderRegistry()
        providers.register(provider)
        with tempfile.TemporaryDirectory() as tmp:
            result=AutonomousRepairLoop(providers,"fake","go",(".go",)).run(
                Path(tmp),"golang:test",initial_validation=validation("BLOCKED"))
        self.assertEqual(result.status,"BLOCKED")
        self.assertEqual(provider.requests,[])

    def test_unchanged_output_does_not_trigger_repeated_repair(self):
        original="package main\n"
        provider=FakeProvider({"files":[{"path":"main.go","content":original}],"rationale":"No safe change."})
        providers=ProviderRegistry()
        providers.register(provider)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"main.go").write_text(original,encoding="utf-8")
            result=AutonomousRepairLoop(providers,"fake","go",(".go",)).run(
                root,"golang:test",initial_validation=validation("FAILED","FAILED","main.go: error"))
        self.assertEqual(result.status,"UNRESOLVED")
        self.assertEqual(result.attempts[0].status,"NO_CHANGES")


if __name__ == "__main__":
    unittest.main()
