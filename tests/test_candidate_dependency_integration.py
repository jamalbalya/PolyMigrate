"""Candidate-specific dependency proof requires declaration, import, and executed gates."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from polymigrate.cli import _candidate_dependency_integration_status
from polymigrate.validation.dependency_wiring import review_dependency_wiring


class CandidateDependencyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.review = SimpleNamespace(
            status="PASSED",
            declared_dependencies=("github.com/acme/dep",),
            observed_imports=("github.com/acme/dep",),
        )
        self.gates = {
            "target_build": "PASSED",
            "integration_tests": "PASSED",
            "behavior_comparison": "PASSED",
        }
        self.candidate = {
            "decision_type": "candidate",
            "selected_package": {"name": "github.com/acme/dep", "registry": "go-modules"},
        }

    def test_no_candidate_dependency_makes_gate_not_applicable(self):
        status, warnings = _candidate_dependency_integration_status([], self.review, self.gates, "python")
        self.assertEqual(status, "PASSED")
        self.assertIn("not applicable", warnings[0])

    def test_candidate_passes_only_when_declared_imported_and_all_required_gates_pass(self):
        status, warnings = _candidate_dependency_integration_status(
            [self.candidate], self.review, self.gates, "go"
        )
        self.assertEqual(status, "PASSED")
        self.assertIn("Each candidate package is declared and imported", warnings[0])

    def test_missing_import_does_not_pass_candidate_proof(self):
        review = SimpleNamespace(
            status="PASSED",
            declared_dependencies=("github.com/acme/dep",),
            observed_imports=("encoding/json",),
        )
        status, warnings = _candidate_dependency_integration_status(
            [self.candidate], review, self.gates, "go"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("not observed", warnings[0])

    def test_integration_gate_must_have_passed(self):
        gates = {**self.gates, "integration_tests": "NOT_RUN"}
        status, warnings = _candidate_dependency_integration_status(
            [self.candidate], self.review, gates, "go"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("integration_tests=PASSED", warnings[0])


    def test_python_candidate_without_matching_declaration_stays_unverified(self):
        candidate = {
            "decision_type": "candidate",
            "selected_package": {"name": "requests", "registry": "pypi"},
        }
        status, warnings = _candidate_dependency_integration_status(
            [candidate], self.review, self.gates, "python"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("not proven present", warnings[0])

    def test_python_candidate_is_proven_by_real_local_package_build_and_integration_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "localdep"
            package.mkdir()
            (package / "__init__.py").write_text(
                """def value():
    return "verified"
""",
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text(
                """localdep==0.1.0
""",
                encoding="utf-8",
            )
            (root / "main.py").write_text(
                """import localdep
print(localdep.value())
""",
                encoding="utf-8",
            )
            tests = root / "tests" / "integration"
            tests.mkdir(parents=True)
            (tests / "test_dependency.py").write_text(
                """import unittest
import localdep
class DependencyIntegrationTest(unittest.TestCase):
    def test_dependency_api(self):
        self.assertEqual(localdep.value(), "verified")
""",
                encoding="utf-8",
            )
            compile_result = subprocess.run(
                ("python", "-m", "compileall", "-q", "."),
                cwd=root, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            integration = subprocess.run(
                ("python", "-m", "unittest", "discover", "-s", "tests/integration", "-v"),
                cwd=root, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(integration.returncode, 0, integration.stderr)
            behavior = subprocess.run(
                ("python", "main.py"), cwd=root, capture_output=True, text=True,
                timeout=30, check=False,
            )
            self.assertEqual(behavior.returncode, 0, behavior.stderr)
            self.assertEqual(behavior.stdout, "verified\n")
            review = review_dependency_wiring(root, "python")
            self.assertEqual(review.status, "PASSED")
            candidate = [{
                "decision_type": "candidate",
                "selected_package": {"name": "localdep", "registry": "pypi"},
            }]
            status, _ = _candidate_dependency_integration_status(
                candidate, review,
                {"target_build": "PASSED", "integration_tests": "PASSED",
                 "behavior_comparison": "PASSED"},
                "python",
            )
            self.assertEqual(status, "PASSED")

    def test_go_dependency_candidate_is_proven_by_real_local_module_build_and_integration_test(self):
        if shutil.which("go") is None:
            self.skipTest("Go toolchain is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dep = root / "third_party" / "dep"
            dep.mkdir(parents=True)
            (dep / "go.mod").write_text(
                """module github.com/acme/dep

go 1.23
""",
                encoding="utf-8",
            )
            (dep / "dep.go").write_text(
                """package dep
func Value() string { return "verified" }
""",
                encoding="utf-8",
            )
            (root / "go.mod").write_text(
                """module example.com/app

go 1.23
require github.com/acme/dep v0.0.0
replace github.com/acme/dep => ./third_party/dep
""",
                encoding="utf-8",
            )
            (root / "main.go").write_text(
                """package main
import ("fmt"; "github.com/acme/dep")
func main() { fmt.Println(dep.Value()) }
""",
                encoding="utf-8",
            )
            (root / "main_test.go").write_text(
                """package main
import ("testing"; "github.com/acme/dep")
func TestDependencyIntegration(t *testing.T) {
    if dep.Value() != "verified" { t.Fatal("unexpected dependency behavior") }
}
""",
                encoding="utf-8",
            )
            env = {**os.environ, "GOTOOLCHAIN": "local", "GOPROXY": "off"}
            for command in (("go", "build", "./..."), ("go", "test", "./...")):
                result = subprocess.run(
                    command, cwd=root, env=env, capture_output=True, text=True,
                    timeout=60, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr[-4000:])
            behavior = subprocess.run(
                ("go", "run", "."), cwd=root, env=env, capture_output=True,
                text=True, timeout=60, check=False,
            )
            self.assertEqual(behavior.returncode, 0, behavior.stderr[-4000:])
            self.assertEqual(behavior.stdout, "verified\n")
            review = review_dependency_wiring(root, "go")
            self.assertEqual(review.status, "PASSED")
            gates = {**self.gates, "behavior_comparison": "PASSED"}
            status, _ = _candidate_dependency_integration_status(
                [self.candidate], review, gates, "go"
            )
            self.assertEqual(status, "PASSED")

    def test_repository_reference_is_not_a_package_integration_proof(self):
        candidate = {
            "decision_type": "candidate",
            "selected_package": {"name": "owner/repository", "registry": "github-repositories"},
        }
        status, warnings = _candidate_dependency_integration_status(
            [candidate], self.review, self.gates, "go"
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("without a package identity", warnings[0])


if __name__ == "__main__":
    unittest.main()
