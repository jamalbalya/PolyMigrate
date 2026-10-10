"""CLI reports a failed sandbox validation as blocked and returns a non-zero code."""
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.cli import main


class FakeProvider:
    provider_id = "fake"
    def get_capabilities(self): return ProviderCapabilities()
    def generate(self, request: ModelRequest):
        return ModelResponse(json.dumps({"content":"package main","assumptions":[],"unsupported_features":[]}),"fake","test")


class ValidationReportCLITests(unittest.TestCase):
    def test_high_risk_generated_output_blocks_migration_without_echoing_secret(self):
        class DangerousProvider(FakeProvider):
            def generate(self, request: ModelRequest):
                return ModelResponse(
                    json.dumps({
                        "content": 'package main\nconst API_KEY = "sk-12345678901234567890"\n',
                        "assumptions": [], "unsupported_features": [],
                    }),
                    "fake", "test",
                )

        registry = ProviderRegistry()
        registry.register(DangerousProvider())
        gates = {"target_build": "NOT_RUN", "unit_tests": "NOT_RUN",
                 "integration_tests": "NOT_RUN", "e2e_tests": "NOT_RUN",
                 "behavior_comparison": "NOT_RUN", "security_review": "NOT_RUN"}
        validation = SimpleNamespace(
            gates=gates, executions=(), warnings=(),
            to_dict=lambda: {"gates": gates, "executions": [], "warnings": []},
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            output = Path(tmp) / "out"
            stdout, stderr = StringIO(), StringIO()
            repair_result = SimpleNamespace(
                validation=validation, warnings=(),
                to_dict=lambda: {"status": "UNRESOLVED", "attempts": [], "warnings": []},
            )
            with patch("polymigrate.cli.build_provider_registry", return_value=(registry, ())), \
                 patch("polymigrate.cli.validate_generated_project", return_value=validation), \
                 patch("polymigrate.cli.AutonomousRepairLoop") as repair_loop, \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                repair_loop.return_value.run.return_value = repair_result
                code = main([
                    "migrate", "--source", str(source), "--from", "python", "--to", "go",
                    "--output", str(output), "--provider", "fake", "--allow-source-upload",
                ])
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 3)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["static_security_scan"]["status"], "FAILED")
        self.assertNotIn("sk-12345678901234567890", json.dumps(report))
        self.assertTrue(any("SECRET_TOKEN_LITERAL" in item for item in report["warnings"]))

    def test_failed_build_marks_report_blocked_and_returns_three(self):
        registry=ProviderRegistry()
        registry.register(FakeProvider())
        gates={"target_build":"FAILED","unit_tests":"NOT_RUN","integration_tests":"NOT_RUN",
               "e2e_tests":"NOT_RUN","behavior_comparison":"NOT_RUN","security_review":"NOT_RUN"}
        validation=SimpleNamespace(gates=gates,executions=(),warnings=("build failed",),to_dict=lambda:{"gates":gates,"executions":[],"warnings":["build failed"]})
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"source"
            source.mkdir()
            (source/"main.py").write_text("print('hello')",encoding="utf-8")
            output=Path(tmp)/"out"
            stdout,stderr=StringIO(),StringIO()
            repair_result=SimpleNamespace(validation=validation,warnings=(),to_dict=lambda:{"status":"UNRESOLVED","attempts":[],"warnings":[]})
            with patch.dict(os.environ,{"POLYMIGRATE_DOCKER_IMAGE_GO":"golang:test"}), \
                 patch("polymigrate.cli.build_provider_registry",return_value=(registry,())), \
                 patch("polymigrate.cli.validate_generated_project",return_value=validation), \
                 patch("polymigrate.cli.AutonomousRepairLoop") as repair_loop, \
                 redirect_stdout(stdout),redirect_stderr(stderr):
                repair_loop.return_value.run.return_value=repair_result
                code=main(["migrate","--source",str(source),"--from","python","--to","go",
                           "--output",str(output),"--provider","fake","--allow-source-upload"])
            report=json.loads((output/"migration-review.json").read_text(encoding="utf-8"))
        self.assertEqual(code,3)
        self.assertEqual(report["status"],"BLOCKED")
        self.assertEqual(report["validation_gates"]["target_build"],"FAILED")
        self.assertIn(report["static_security_scan"]["status"], {"PASSED", "REVIEW_REQUIRED"})
        self.assertTrue(report["static_security_scan"]["not_a_comprehensive_audit"])
        self.assertIn("dependency_wiring_review", report)
        self.assertTrue(report["dependency_wiring_review"]["does_not_prove_build_or_api_compatibility"])
        self.assertEqual(report["validation_gates"]["security_review"], "NOT_RUN")


if __name__ == "__main__":
    unittest.main()
