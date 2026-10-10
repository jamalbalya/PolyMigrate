"""Language-aware validation command selection and sandbox result aggregation."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

from polymigrate.validation.runner import DockerSandboxRunner, SandboxExecution, ValidationCommand

@dataclass(frozen=True)
class ValidationSuiteResult:
    gates: dict[str, str]
    executions: tuple[SandboxExecution, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "gates": dict(self.gates),
            "executions": [
                {
                    "command_id": item.command_id, "status": item.status, "image": item.image,
                    "exit_code": item.exit_code, "duration_seconds": item.duration_seconds,
                    "stdout": item.stdout, "stderr": item.stderr, "details": item.details,
                } for item in self.executions
            ],
            "warnings": list(self.warnings),
        }


def _commands_for_project(workspace: Path, language_id: str) -> tuple[list[ValidationCommand], list[str]]:
    commands: list[ValidationCommand] = []
    warnings: list[str] = []
    if language_id == "python":
        if list(workspace.rglob("*.py")):
            commands.append(ValidationCommand("build-python-compile", ("python", "-m", "compileall", "-q", ".")))
        tests_dir = workspace / "tests"
        if tests_dir.is_dir() and any(t.is_file() and (t.name.startswith("test_") or t.name.endswith("_test.py")) for t in tests_dir.rglob("*.py")):
            commands.append(ValidationCommand("unit_tests-python", ("python", "-m", "unittest", "discover", "-s", "tests", "-v")))
        else:
            warnings.append("Python unit tests were not run because no test files were found in tests/.")
    elif language_id == "go":
        go_files = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*.go") if not any(part in {".git", "vendor"} for part in p.relative_to(workspace).parts))
        module_mode = () if (workspace / "go.mod").is_file() else (("GO111MODULE", "off"),)
        if go_files:
            commands.append(ValidationCommand("build-go", ("go", "build", "./..."), environment=module_mode))
        if any(path.endswith("_test.go") for path in go_files):
            commands.append(ValidationCommand("unit_tests-go", ("go", "test", "./..."), environment=module_mode))
        else:
            warnings.append("Go unit tests were not run because no *_test.go files were found.")
    elif language_id in {"javascript", "typescript"}:
        package_scripts = {}
        package_file = workspace / "package.json"
        if package_file.is_file():
            try:
                package = json.loads(package_file.read_text(encoding="utf-8"))
                package_scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
                if not isinstance(package_scripts, dict):
                    package_scripts = {}
            except (OSError, UnicodeError, json.JSONDecodeError):
                warnings.append("Node package.json could not be read; package scripts were not executed.")
        if "build" in package_scripts:
            commands.append(ValidationCommand("build-node", ("npm", "run", "build")))
        elif language_id == "javascript":
            files = sorted({
                p.relative_to(workspace).as_posix()
                for pattern in ("*.js", "*.mjs", "*.cjs")
                for p in workspace.rglob(pattern)
                if not any(part in {".git", "node_modules", "dist", "build"} for part in p.relative_to(workspace).parts)
            })
            commands.extend(ValidationCommand(f"build-js-syntax-{i}", ("node", "--check", path)) for i, path in enumerate(files))
            if any(workspace.rglob("*.jsx")):
                warnings.append("JSX files require a configured build script; node --check does not validate JSX syntax.")
        elif (workspace / "tsconfig.json").is_file():
            commands.append(ValidationCommand("build-typescript", ("tsc", "--noEmit")))
        if "test" in package_scripts:
            commands.append(ValidationCommand("unit_tests-node", ("npm", "test")))
        elif package_file.is_file():
            warnings.append("Node unit tests were not run because package.json has no test script.")
    elif language_id == "java":
        if (workspace / "pom.xml").is_file():
            commands.append(ValidationCommand("build-java", ("mvn", "-B", "-DskipTests", "package")))
            commands.append(ValidationCommand("unit_tests-java", ("mvn", "-B", "test")))
        else:
            files = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*.java") if not any(part in {".git", "target", "build"} for part in p.relative_to(workspace).parts))
            if files:
                commands.append(ValidationCommand("build-java-compile", ("javac", "-d", "/tmp", *files)))
    elif language_id == "rust" and (workspace / "Cargo.toml").is_file():
        commands.extend([ValidationCommand("build-rust", ("cargo", "check")),
                         ValidationCommand("unit_tests-rust", ("cargo", "test"))])
    elif language_id == "csharp":
        if list(workspace.glob("*.sln")) or list(workspace.glob("*.csproj")):
            commands.extend([ValidationCommand("build-csharp", ("dotnet", "build")),
                             ValidationCommand("unit_tests-csharp", ("dotnet", "test"))])
    elif language_id in {"c", "cpp"}:
        suffixes = ("*.c",) if language_id == "c" else ("*.cc", "*.cpp", "*.cxx")
        files = sorted({p.relative_to(workspace).as_posix() for suffix in suffixes for p in workspace.rglob(suffix) if not any(part in {".git", "build", "dist"} for part in p.relative_to(workspace).parts)})
        compiler = "gcc" if language_id == "c" else "g++"
        commands.extend(ValidationCommand(f"build-native-syntax-{i}", (compiler, "-fsyntax-only", path)) for i, path in enumerate(files))
    elif language_id == "swift":
        files = sorted(p.relative_to(workspace).as_posix() for p in workspace.rglob("*.swift") if not any(part in {".git", ".build"} for part in p.relative_to(workspace).parts))
        commands.extend(ValidationCommand(f"build-swift-typecheck-{i}", ("swiftc", "-typecheck", path)) for i, path in enumerate(files))
        if (workspace / "Package.swift").is_file():
            commands.append(ValidationCommand("unit_tests-swift", ("swift", "test")))
    if not commands:
        warnings.append(f"No safe default validation commands are available for target language '{language_id}' and the generated project layout.")
    return commands, warnings


def validate_generated_project(workspace: Path, language_id: str, image: str | None,
                               runner: DockerSandboxRunner | None = None) -> ValidationSuiteResult:
    gates = {
        "target_build": "NOT_RUN", "unit_tests": "NOT_RUN", "integration_tests": "NOT_RUN",
        "e2e_tests": "NOT_RUN", "behavior_comparison": "NOT_RUN", "security_review": "NOT_RUN",
    }
    if not image:
        return ValidationSuiteResult(gates, (), (
            f"No local Docker validation image configured for {language_id}; build/test gates were not run.",
        ))
    commands, warnings = _commands_for_project(workspace, language_id)
    runner = runner or DockerSandboxRunner()
    executions: list[SandboxExecution] = []
    build_failed = False
    for command in commands:
        if build_failed and command.command_id.startswith("unit_tests"):
            warnings.append(f"Skipped {command.command_id} because a build gate failed.")
            continue
        execution = runner.run(workspace, image, command)
        executions.append(execution)
        if command.command_id.startswith("build"):
            if execution.status != "PASSED":
                gates["target_build"] = execution.status
                build_failed = True
            elif gates["target_build"] == "NOT_RUN":
                gates["target_build"] = "PASSED"
        elif command.command_id.startswith("unit_tests"):
            gates["unit_tests"] = execution.status
    return ValidationSuiteResult(gates, tuple(executions), tuple(warnings))
