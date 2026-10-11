"""End-to-end CLI tests for experimental migration with a deterministic fake model."""
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

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
            self.assertEqual(code, 3, stderr.getvalue())
            report = json.loads((output / "migration-review.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["validation_gates"]["target_build"], "NOT_RUN")
            self.assertEqual(report["validation_gates"]["dependency_integration"], "NOT_RUN")
            self.assertTrue(any("Dependency-gap planning emitted warnings" in warning for warning in report["warnings"]))
            self.assertTrue((output / "main.go").is_file())
            self.assertEqual(source_file.read_text(encoding="utf-8"), "print('hello')")

    def test_deterministic_migration_never_initializes_ai_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            output = Path(tmp) / "out"
            stdout, stderr = StringIO(), StringIO()
            with patch("polymigrate.cli.build_provider_registry") as build_registry:
                with patch("polymigrate.cli.shutil.which", return_value=None):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main([
                            "migrate", "--source", str(source), "--from", "python",
                            "--to", "go", "--output", str(output),
                            "--strategy", "deterministic",
                        ])
            build_registry.assert_not_called()
            self.assertEqual(code, 3, stderr.getvalue())
            generated = (output / "main.go").read_text(encoding="utf-8")
            self.assertIn("fmt.Println(42)", generated)
            report = json.loads(
                (output / "migration-review.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["strategy"], "deterministic")
            self.assertEqual(report["status"], "BLOCKED")
            self.assertEqual(report["validation_gates"]["target_build"], "BLOCKED")
            self.assertIn("No source code is sent", report["note"])
            self.assertFalse(any(
                warning.startswith("Generated output has not yet passed")
                or warning == "Generated output must pass build, test, security, and behavior checks."
                for warning in report["warnings"]
            ))
            self.assertTrue(any(
                "No behavior spec was supplied" in warning
                for warning in report["warnings"]
            ))

    def test_deterministic_scan_blocks_when_trusted_scanners_are_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            output = Path(tmp) / "out"
            stdout, stderr = StringIO(), StringIO()

            scan = MagicMock()
            scan.status = "PASSED"
            scan.warnings = (
                "This bounded heuristic scan is not a comprehensive security audit.",
            )
            scan.findings = ()
            scan.to_dict.return_value = {
                "status": "PASSED",
                "scope": "bounded_static_heuristics",
                "findings": [],
                "warnings": list(scan.warnings),
                "not_a_comprehensive_audit": True,
            }

            with patch(
                "polymigrate.cli.review_generated_output",
                return_value=scan,
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main([
                        "migrate", "--source", str(source), "--from", "python",
                        "--to", "go", "--output", str(output),
                        "--strategy", "deterministic",
                    ])

            report = json.loads(
                (output / "migration-review.json").read_text(encoding="utf-8")
            )

        self.assertEqual(code, 3, stderr.getvalue())
        self.assertEqual(report["static_security_scan"]["status"], "PASSED")
        self.assertTrue(
            report["static_security_scan"]["not_a_comprehensive_audit"]
        )
        self.assertEqual(report["local_security_scan"]["status"], "INCOMPLETE")
        self.assertFalse(report["local_security_scan"]["scanner_provenance_verified"])
        self.assertEqual(report["validation_gates"]["security_review"], "INCOMPLETE")
        self.assertEqual(report["status"], "BLOCKED")

    def test_deterministic_migration_blocks_unverified_dependency_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            output = Path(tmp) / "out"
            stdout, stderr = StringIO(), StringIO()

            review = MagicMock()
            review.status = "UNVERIFIED"
            review.warnings = ("Dependency scan was incomplete.",)
            review.to_dict.return_value = {
                "status": "UNVERIFIED",
                "warnings": ["Dependency scan was incomplete."],
            }

            with patch(
                "polymigrate.cli.review_dependency_wiring",
                return_value=review,
            ):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main([
                        "migrate", "--source", str(source), "--from", "python",
                        "--to", "go", "--output", str(output),
                        "--strategy", "deterministic",
                    ])

            self.assertEqual(
                code, 3,
                f"CLI exit code was {code}; stderr={stderr.getvalue()!r}; "
                f"stdout={stdout.getvalue()!r}"
            )
            report = json.loads(
                (output / "migration-review.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "BLOCKED")
            self.assertIn("Dependency scan was incomplete.", report["warnings"])

    def test_deterministic_report_records_behavior_and_configured_suite_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            spec = root / "behavior.json"
            spec.write_text("{}", encoding="utf-8")
            output = root / "out"
            stdout, stderr = StringIO(), StringIO()

            comparison = MagicMock()
            comparison.status = "PASSED"
            comparison.to_dict.return_value = {
                "status": "PASSED",
                "cases_checked": 1,
                "executions": [],
                "warnings": ["Only the supplied behavior case was checked."],
            }
            suite = MagicMock()
            suite.gates = {
                "target_build": "PASSED",
                "unit_tests": "NOT_RUN",
                "integration_tests": "NOT_RUN",
                "e2e_tests": "NOT_RUN",
            }
            suite.executions = ()
            suite.warnings = ("No Go test files were found.",)
            suite.to_dict.return_value = {"executions": []}

            fake_process = MagicMock(returncode=0, stdout="", stderr="")
            with patch.dict("os.environ", {
                "POLYMIGRATE_DOCKER_IMAGE_GO": "golang:1.23-alpine",
                "POLYMIGRATE_DOCKER_IMAGE_PYTHON": "python:3.12-slim",
            }), patch("polymigrate.cli.shutil.which", side_effect=lambda name: {
                "go": "/fake/go", "gofmt": "/fake/gofmt"
            }.get(name)), patch("polymigrate.cli.subprocess.run", return_value=fake_process), patch(
                "polymigrate.cli.validate_generated_project", return_value=suite
            ) as validate_suite, patch(
                "polymigrate.cli.compare_behavior", return_value=comparison
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "go", "--output", str(output),
                    "--strategy", "deterministic", "--behavior-spec", str(spec),
                ])

            self.assertEqual(code, 3, stderr.getvalue())
            validate_suite.assert_called_once()
            self.assertEqual(validate_suite.call_args.args[1:], ("go", "golang:1.23-alpine"))
            report = json.loads(
                (output / "migration-review.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["behavior_comparison"]["status"], "PASSED")
            self.assertEqual(report["validation_gates"]["behavior_comparison"], "PASSED")
            self.assertEqual(report["validation_gates"]["unit_tests"], "NOT_RUN")
            self.assertEqual(report["validation_gates"]["integration_tests"], "NOT_RUN")
            self.assertEqual(report["validation_gates"]["e2e_tests"], "NOT_RUN")
            self.assertEqual(report["validation_image"], "golang:1.23-alpine")
            self.assertEqual(report["status"], "BLOCKED")

    def test_deterministic_migration_rejects_unsupported_language_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print(42)\n", encoding="utf-8")
            output = Path(tmp) / "out"
            stderr = StringIO()
            with redirect_stderr(stderr):
                code = main([
                    "migrate", "--source", str(source), "--from", "python",
                    "--to", "ruby", "--output", str(output),
                    "--strategy", "deterministic",
                ])
            self.assertEqual(code, 2)
            self.assertIn("supports --from python --to go", stderr.getvalue().lower())
            self.assertFalse(output.exists())

    def test_migrate_requires_source_upload_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            (source / "main.py").write_text("print('hello')", encoding="utf-8")
            output = Path(tmp) / "out"
            stderr = StringIO()
            with patch("polymigrate.cli.build_provider_registry", return_value=(self.registry, ())) as build_registry, redirect_stderr(stderr):
                code = main(["migrate", "--source", str(source), "--from", "python", "--to", "go",
                             "--output", str(output), "--provider", "fake"])
            build_registry.assert_not_called()
            self.assertEqual(code, 2)
            self.assertIn("Source upload is disabled", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
