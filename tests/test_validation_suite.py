"""Validation suite tests use a fake runner and never require Docker."""
import tempfile
import unittest
from pathlib import Path

from polymigrate.validation.runner import SandboxExecution
from polymigrate.validation.suite import validate_generated_project


class FakeRunner:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.commands = []
    def run(self, workspace, image, command):
        self.commands.append(command)
        status = next(self.statuses)
        return SandboxExecution(command.command_id, status, image,
                               0 if status == "PASSED" else 1, 0.01,
                               details="fake validation result")


class ValidationSuiteTests(unittest.TestCase):
    def test_no_image_means_validation_is_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = validate_generated_project(Path(tmp), "python", None)
        self.assertTrue(all(value == "NOT_RUN" for value in result.gates.values()))
        self.assertIn("No local Docker validation image configured", result.warnings[0])

    def test_python_build_and_unit_tests_run_in_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("print('hello')", encoding="utf-8")
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text("def test_smoke(): pass", encoding="utf-8")
            runner = FakeRunner(["PASSED", "PASSED"])
            result = validate_generated_project(root, "python", "python:3.13", runner)
        self.assertEqual(result.gates["target_build"], "PASSED")
        self.assertEqual(result.gates["unit_tests"], "PASSED")
        self.assertEqual(len(runner.commands), 2)

    def test_build_failure_skips_unit_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_text("print('hello')", encoding="utf-8")
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_app.py").write_text("def test_smoke(): pass", encoding="utf-8")
            runner = FakeRunner(["FAILED"])
            result = validate_generated_project(root, "python", "python:3.13", runner)
        self.assertEqual(result.gates["target_build"], "FAILED")
        self.assertEqual(result.gates["unit_tests"], "NOT_RUN")
        self.assertEqual(len(runner.commands), 1)
        self.assertTrue(any("Skipped unit_tests" in warning for warning in result.warnings))

    def test_unsupported_layout_is_reported_not_assumed_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = validate_generated_project(root, "kotlin", "kotlin:latest", FakeRunner([]))
        self.assertTrue(all(value == "NOT_RUN" for value in result.gates.values()))
        self.assertTrue(any("No safe default validation commands" in warning for warning in result.warnings))


    def test_kotlin_compiler_command_is_selected_without_running_build_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Main.kt").write_text("fun main() = println(42)\n", encoding="utf-8")
            runner = FakeRunner(["PASSED"])
            result = validate_generated_project(root, "kotlin", "kotlin:latest", runner)
        self.assertEqual(result.gates["target_build"], "PASSED")
        self.assertEqual(runner.commands[0].argv, (
            "kotlinc", "Main.kt", "-d", "/tmp/polymigrate-validation.jar"
        ))
        self.assertTrue(any("dependency resolution" in warning for warning in result.warnings))

    def test_ruby_sources_receive_syntax_checks_but_no_test_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.rb").write_text("puts 42\n", encoding="utf-8")
            runner = FakeRunner(["PASSED"])
            result = validate_generated_project(root, "ruby", "ruby:latest", runner)
        self.assertEqual(result.gates["target_build"], "PASSED")
        self.assertEqual(result.gates["unit_tests"], "NOT_RUN")
        self.assertEqual(runner.commands[0].argv, ("ruby", "-c", "main.rb"))
        self.assertTrue(any("syntax only" in warning for warning in result.warnings))

    def test_php_sources_receive_lint_checks_but_no_test_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "index.php").write_text("<?php echo 42;\n", encoding="utf-8")
            runner = FakeRunner(["PASSED"])
            result = validate_generated_project(root, "php", "php:latest", runner)
        self.assertEqual(result.gates["target_build"], "PASSED")
        self.assertEqual(result.gates["unit_tests"], "NOT_RUN")
        self.assertEqual(runner.commands[0].argv, ("php", "-l", "index.php"))
        self.assertTrue(any("Composer dependency resolution" in warning for warning in result.warnings))

    def test_go_without_module_uses_legacy_module_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.go").write_text("package main", encoding="utf-8")
            (root / "main_test.go").write_text("package main", encoding="utf-8")
            runner = FakeRunner(["PASSED", "PASSED", "PASSED"])
            result = validate_generated_project(root, "go", "golang:latest", runner)
        self.assertEqual(result.gates["target_build"], "PASSED")
        self.assertEqual(result.gates["unit_tests"], "PASSED")
        self.assertEqual(runner.commands[0].argv, ("go", "build", "./..."))
        self.assertEqual(runner.commands[1].argv, ("go", "vet", "./..."))
        self.assertEqual(runner.commands[0].environment, (("GO111MODULE", "off"),))
        self.assertEqual(runner.commands[1].environment, (("GO111MODULE", "off"),))

    def test_go_vet_failure_blocks_unit_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "go.mod").write_text("module example.test/app", encoding="utf-8")
            (root / "main.go").write_text("package main", encoding="utf-8")
            (root / "main_test.go").write_text("package main", encoding="utf-8")
            runner = FakeRunner(["PASSED", "FAILED"])
            result = validate_generated_project(root, "go", "golang:latest", runner)
        self.assertEqual(result.gates["target_build"], "FAILED")
        self.assertEqual(result.gates["unit_tests"], "NOT_RUN")
        self.assertEqual([command.command_id for command in runner.commands], ["build-go", "build-go-vet"])
        self.assertTrue(any("Skipped unit_tests-go" in warning for warning in result.warnings))

    def test_go_module_project_keeps_module_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "go.mod").write_text("module example.test/app", encoding="utf-8")
            (root / "main.go").write_text("package main", encoding="utf-8")
            runner = FakeRunner(["PASSED", "PASSED"])
            result = validate_generated_project(root, "go", "golang:latest", runner)
        self.assertEqual(result.gates["target_build"], "PASSED")
        self.assertEqual(runner.commands[0].argv, ("go", "build", "./..."))
        self.assertEqual(runner.commands[1].argv, ("go", "vet", "./..."))
        self.assertEqual(runner.commands[0].environment, ())
        self.assertEqual(runner.commands[1].environment, ())

    def test_pytest_function_style_is_not_silently_run_with_unittest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"main.py").write_text("print('hello')",encoding="utf-8")
            tests=root/"tests"
            tests.mkdir()
            (tests/"test_app.py").write_text("def test_smoke(): assert True\n",encoding="utf-8")
            runner=FakeRunner(["PASSED","PASSED"])
            validate_generated_project(root,"python","python:3.13",runner)
        self.assertEqual(runner.commands[1].argv,("python","-m","pytest","-q","tests"))

    def test_available_python_integration_and_e2e_suites_are_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"main.py").write_text("print('hello')",encoding="utf-8")
            (root/"tests"/"unit").mkdir(parents=True)
            (root/"tests"/"unit"/"test_unit.py").write_text("import unittest\nclass TestUnit(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",encoding="utf-8")
            (root/"tests"/"integration").mkdir()
            (root/"tests"/"integration"/"test_api.py").write_text("import unittest\nclass TestApi(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",encoding="utf-8")
            (root/"tests"/"e2e").mkdir()
            (root/"tests"/"e2e"/"test_flow.py").write_text("import unittest\nclass TestFlow(unittest.TestCase):\n def test_ok(self): self.assertTrue(True)\n",encoding="utf-8")
            runner=FakeRunner(["PASSED","PASSED","PASSED","PASSED"])
            result=validate_generated_project(root,"python","python:3.13",runner)
        self.assertEqual(result.gates["integration_tests"],"PASSED")
        self.assertEqual(result.gates["e2e_tests"],"PASSED")
        self.assertEqual([command.command_id for command in runner.commands],
                         ["build-python-compile","unit_tests-python","integration_tests-python","e2e_tests-python"])


if __name__ == "__main__":
    unittest.main()
