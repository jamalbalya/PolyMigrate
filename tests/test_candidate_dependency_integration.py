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

    def test_unresolved_library_gap_does_not_pass_dependency_integration(self):
        status, warnings = _candidate_dependency_integration_status(
            [{"decision_type": "unresolved", "strategy": "unresolved"}],
            self.review, self.gates, "python",
        )
        self.assertEqual(status, "UNVERIFIED")
        self.assertIn("remain unresolved", warnings[0])

    def test_dependency_planner_warning_does_not_turn_missing_results_into_pass(self):
        status, warnings = _candidate_dependency_integration_status(
            [], self.review, self.gates, "python",
            dependency_warnings=("dependency planning failed",),
        )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("emitted warnings", warnings[0])

    def test_custom_implementation_recommendation_is_not_dependency_integration_proof(self):
        status, warnings = _candidate_dependency_integration_status(
            [{"decision_type": "custom_implementation", "strategy": "custom"}],
            self.review, self.gates, "python",
        )
        self.assertEqual(status, "UNVERIFIED")
        self.assertIn("custom/architectural implementation", warnings[0])

    def test_generic_green_gates_do_not_replace_candidate_specific_test_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, warnings = _candidate_dependency_integration_status(
                [self.candidate], self.review, self.gates, "go", project_root=Path(tmp)
            )
        self.assertEqual(status, "NOT_RUN")
        self.assertIn("No recognized integration/test file imports candidate package", warnings[0])

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


    @unittest.skipUnless(shutil.which("cargo"), "Rust toolchain is required")
    def test_rust_candidate_is_proven_by_real_local_crate_build_and_integration_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "localdep" / "src").mkdir(parents=True)
            (root / "Cargo.toml").write_text(
                '[package]\nname = "fixture-app"\nversion = "0.1.0"\nedition = "2021"\n'
                '[dependencies]\nlocaldep = { path = "localdep" }\n'
                '[workspace]\nmembers = ["localdep"]\n',
                encoding="utf-8",
            )
            (root / "src" / "main.rs").write_text(
                'use localdep::value;\nfn main() { println!("{}", value()); }\n',
                encoding="utf-8",
            )
            (root / "localdep" / "Cargo.toml").write_text(
                '[package]\nname = "localdep"\nversion = "0.1.0"\nedition = "2021"\n',
                encoding="utf-8",
            )
            (root / "localdep" / "src" / "lib.rs").write_text(
                'pub fn value() -> &\'static str { "verified" }\n',
                encoding="utf-8",
            )
            (root / "tests" / "test_dependency.rs").write_text(
                'use localdep::value;\n#[test]\nfn candidate_api_works() { assert_eq!(value(), "verified"); }\n',
                encoding="utf-8",
            )
            build_and_test = subprocess.run(
                ("cargo", "test", "--offline", "--quiet"), cwd=root,
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(build_and_test.returncode, 0, build_and_test.stderr)
            behavior = subprocess.run(
                ("cargo", "run", "--offline", "--quiet"), cwd=root,
                capture_output=True, text=True, timeout=120, check=False,
            )
            self.assertEqual(behavior.returncode, 0, behavior.stderr)
            self.assertEqual(behavior.stdout, "verified\n")
            review = review_dependency_wiring(root, "rust")
            self.assertEqual(review.status, "PASSED", review.warnings)
            candidate = [{
                "decision_type": "candidate",
                "selected_package": {"name": "localdep", "registry": "crates.io"},
            }]
            status, _ = _candidate_dependency_integration_status(
                candidate, review,
                {"target_build": "PASSED", "integration_tests": "PASSED",
                 "behavior_comparison": "PASSED"},
                "rust", project_root=root,
            )
            self.assertEqual(status, "PASSED")

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
                "python", project_root=root,
            )
            self.assertEqual(status, "PASSED")

    def test_javascript_candidate_is_proven_by_real_local_package_build_and_integration_test(self):
        if shutil.which("node") is None:
            self.skipTest("Node.js is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                """{
  "name": "example-app",
  "type": "module",
  "dependencies": {"localdep": "0.1.0"}
}
""",
                encoding="utf-8",
            )
            package = root / "node_modules" / "localdep"
            package.mkdir(parents=True)
            (package / "package.json").write_text(
                """{"name":"localdep","version":"0.1.0","type":"module","exports":"./index.js"}
""",
                encoding="utf-8",
            )
            (package / "index.js").write_text(
                """export function value() { return "verified"; }
""",
                encoding="utf-8",
            )
            (root / "main.js").write_text(
                """import { value } from "localdep";
console.log(value());
""",
                encoding="utf-8",
            )
            tests = root / "tests" / "integration"
            tests.mkdir(parents=True)
            (tests / "test_dependency.js").write_text(
                """import assert from "node:assert/strict";
import { value } from "localdep";
assert.equal(value(), "verified");
""",
                encoding="utf-8",
            )
            build = subprocess.run(
                ("node", "--check", "main.js"), cwd=root, capture_output=True,
                text=True, timeout=30, check=False,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            integration = subprocess.run(
                ("node", "tests/integration/test_dependency.js"), cwd=root,
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(integration.returncode, 0, integration.stderr)
            behavior = subprocess.run(
                ("node", "main.js"), cwd=root, capture_output=True, text=True,
                timeout=30, check=False,
            )
            self.assertEqual(behavior.returncode, 0, behavior.stderr)
            self.assertEqual(behavior.stdout, "verified\n")
            review = review_dependency_wiring(root, "javascript")
            self.assertEqual(review.status, "PASSED")
            candidate = [{
                "decision_type": "candidate",
                "selected_package": {"name": "localdep", "registry": "npm"},
            }]
            status, _ = _candidate_dependency_integration_status(
                candidate, review,
                {"target_build": "PASSED", "integration_tests": "PASSED",
                 "behavior_comparison": "PASSED"},
                "javascript", project_root=root,
            )
            self.assertEqual(status, "PASSED")

    def test_ruby_candidate_is_proven_by_real_local_gem_build_and_integration_test(self):
        if shutil.which("ruby") is None:
            self.skipTest("Ruby is unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Gemfile").write_text(
                """source "https://rubygems.org"
gem "localdep", "0.1.0"
""",
                encoding="utf-8",
            )
            lib = root / "lib"
            lib.mkdir()
            (lib / "localdep.rb").write_text(
                """module Localdep
  def self.value
    "verified"
  end
end
""",
                encoding="utf-8",
            )
            (root / "main.rb").write_text(
                """require "localdep"
puts Localdep.value
""",
                encoding="utf-8",
            )
            tests = root / "tests" / "integration"
            tests.mkdir(parents=True)
            (tests / "test_dependency.rb").write_text(
                """require "localdep"
raise "unexpected dependency behavior" unless Localdep.value == "verified"
""",
                encoding="utf-8",
            )
            for source in ("main.rb", "lib/localdep.rb"):
                build = subprocess.run(
                    ("ruby", "-c", source), cwd=root, capture_output=True,
                    text=True, timeout=30, check=False,
                )
                self.assertEqual(build.returncode, 0, build.stderr)
            integration = subprocess.run(
                ("ruby", "-Ilib", "tests/integration/test_dependency.rb"),
                cwd=root, capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(integration.returncode, 0, integration.stderr)
            behavior = subprocess.run(
                ("ruby", "-Ilib", "main.rb"), cwd=root, capture_output=True,
                text=True, timeout=30, check=False,
            )
            self.assertEqual(behavior.returncode, 0, behavior.stderr)
            self.assertEqual(behavior.stdout, "verified\n")
            review = review_dependency_wiring(root, "ruby")
            self.assertEqual(review.status, "PASSED")
            candidate = [{
                "decision_type": "candidate",
                "selected_package": {"name": "localdep", "registry": "rubygems"},
            }]
            status, _ = _candidate_dependency_integration_status(
                candidate, review,
                {"target_build": "PASSED", "integration_tests": "PASSED",
                 "behavior_comparison": "PASSED"},
                "ruby", project_root=root,
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
                [self.candidate], review, gates, "go", project_root=root
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
