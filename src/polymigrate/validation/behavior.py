"""Optional source-vs-target behavior comparison using isolated, pre-pulled Docker images."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from polymigrate.security.redaction import redact_text
from polymigrate.validation.runner import DockerSandboxRunner, SandboxExecution, ValidationCommand

_IGNORED_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
    ".pytest_cache", "dist", "build", "target", "vendor", ".next",
}
_ALLOWED_EXECUTABLES = {
    "python", "python3", "node", "go", "cargo", "rustc", "java", "javac",
    "dotnet", "ruby", "php", "swift", "gcc", "g++", "clang", "clang++",
    "mvn", "gradle", "cmake", "make", "npm", "npx", "pytest", "tsc",
    "composer", "bundle", "gem",
}
_INLINE_EXECUTION_FLAGS = {"-c", "-e", "--eval", "--command", "-command"}


@dataclass(frozen=True)
class BehaviorComparisonResult:
    status: str
    executions: tuple[SandboxExecution, ...]
    warnings: tuple[str, ...]
    cases_checked: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cases_checked": self.cases_checked,
            "executions": [
                {
                    "command_id": item.command_id, "status": item.status,
                    "image": item.image, "exit_code": item.exit_code,
                    "duration_seconds": item.duration_seconds,
                    "stdout": item.stdout, "stderr": item.stderr, "details": item.details,
                }
                for item in self.executions
            ],
            "warnings": list(self.warnings),
        }


def _command(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > 30:
        raise ValueError(f"Behavior spec {label} must be a non-empty argv array with at most 30 entries")
    if any(not isinstance(item, str) or not item or "\x00" in item or len(item) > 1024 for item in value):
        raise ValueError(f"Behavior spec {label} contains an invalid argv entry")
    executable = Path(value[0]).name.lower()
    if executable not in _ALLOWED_EXECUTABLES:
        raise ValueError(f"Behavior spec {label} uses a non-allowlisted executable")
    if any(item.lower() in _INLINE_EXECUTION_FLAGS for item in value[1:]):
        raise ValueError(f"Behavior spec {label} may not use inline-code execution flags")
    for item in value[1:]:
        normalized = item.replace("\\", "/")
        if PurePosixPath(normalized).is_absolute() or ".." in PurePosixPath(normalized).parts:
            raise ValueError(f"Behavior spec {label} arguments must not use absolute paths or parent traversal")
    return tuple(value)


def _copy_project_snapshot(source: Path, destination: Path, *, max_files: int = 10_000,
                           max_total_bytes: int = 50_000_000) -> None:
    if source.is_symlink():
        raise ValueError("Behavior comparison workspace must not be a symlink")
    root = source.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Behavior comparison workspace must be a real directory")
    destination.mkdir(parents=True, exist_ok=False)
    files_copied = 0
    total_bytes = 0
    for current, directories, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in _IGNORED_DIRS and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink() or not path.is_file():
                continue
            files_copied += 1
            if files_copied > max_files:
                raise ValueError(f"Behavior comparison snapshot exceeds {max_files} files")
            size = path.stat().st_size
            if total_bytes + size > max_total_bytes:
                raise ValueError(f"Behavior comparison snapshot exceeds {max_total_bytes} bytes")
            relative = path.relative_to(root)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            total_bytes += size
    if files_copied == 0:
        raise ValueError("Behavior comparison snapshot contains no regular files")


def _validate_spec(spec_path: Path) -> tuple[tuple[str, ...], tuple[str, ...], list[dict[str, Any]]]:
    resolved = spec_path.expanduser().resolve(strict=True)
    if not resolved.is_file() or resolved.stat().st_size > 100_000:
        raise ValueError("Behavior spec must be a regular JSON file no larger than 100 KB")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Behavior spec is unreadable or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Behavior spec must be a JSON object")
    source_command = _command(payload.get("source_command"), "source_command")
    target_command = _command(payload.get("target_command"), "target_command")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 10:
        raise ValueError("Behavior spec must contain between 1 and 10 cases")
    validated: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"Behavior case {index} must be an object")
        name = case.get("name", f"case-{index}")
        expected = case.get("expected_stdout")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError(f"Behavior case {index} has an invalid name")
        if not isinstance(expected, str) or len(expected) > 10_000:
            raise ValueError(f"Behavior case {name} requires expected_stdout (up to 10000 characters)")
        source_args = case.get("source_args", [])
        target_args = case.get("target_args", [])
        if not isinstance(source_args, list) or not isinstance(target_args, list):
            raise ValueError(f"Behavior case {name} arguments must be arrays")
        source_argv = _command(list(source_command) + source_args, f"case {name} source argv")
        target_argv = _command(list(target_command) + target_args, f"case {name} target argv")
        validated.append({
            "name": name, "source_argv": source_argv, "target_argv": target_argv,
            "expected_stdout": expected.replace("\r\n", "\n"),
        })
    return source_command, target_command, validated


def _command_environment(workspace: Path, argv: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    executable = Path(argv[0]).name.lower()
    if executable == "go":
        return (
            ("GOCACHE", "/workspace/.polymigrate-gocache"),
            ("GOTMPDIR", "/workspace/.polymigrate-gotmp"),
            ("GOPATH", "/workspace/.polymigrate-gopath"),
            ("GOMODCACHE", "/workspace/.polymigrate-gomodcache"),
            ("GOPROXY", "off"), ("GOSUMDB", "off"), ("GOTOOLCHAIN", "local"),
            ("GO111MODULE", "on" if (workspace / "go.mod").is_file() else "off"),
        )
    if executable == "cargo":
        return (
            ("CARGO_HOME", "/workspace/.cargo-home"),
            ("CARGO_TARGET_DIR", "/workspace/.cargo-target"),
            ("CARGO_NET_OFFLINE", "true"),
        )
    if executable in {"npm", "npx"}:
        return (("npm_config_offline", "true"), ("NPM_CONFIG_UPDATE_NOTIFIER", "false"))
    return ()


def compare_behavior(
    spec_path: Path, source_root: Path, target_root: Path,
    source_image: str | None, target_image: str | None,
    runner: DockerSandboxRunner | None = None,
) -> BehaviorComparisonResult:
    """Compare source and generated output without executing either project on the host."""
    source_command, target_command, cases = _validate_spec(spec_path)
    if not source_image or not target_image:
        return BehaviorComparisonResult(
            "BLOCKED", (), ("Behavior comparison requires preconfigured source and target Docker images; no images were pulled.",)
        )
    sandbox = runner or DockerSandboxRunner()
    executions: list[SandboxExecution] = []
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="polymigrate-behavior-") as tmp:
        root = Path(tmp)
        source_snapshot = root / "source"
        target_snapshot = root / "target"
        try:
            _copy_project_snapshot(source_root, source_snapshot)
            _copy_project_snapshot(target_root, target_snapshot)
        except (OSError, ValueError) as exc:
            return BehaviorComparisonResult(
                "BLOCKED", (), (redact_text(f"Behavior comparison snapshot failed ({type(exc).__name__})."),)
            )
        failed = False
        blocked = False
        timed_out = False
        for index, case in enumerate(cases, start=1):
            source_result = sandbox.run(
                source_snapshot, source_image,
                ValidationCommand(
                    f"behavior_source_{index}", case["source_argv"], timeout_seconds=20.0,
                    environment=_command_environment(source_snapshot, case["source_argv"]),
                ),
            )
            target_result = sandbox.run(
                target_snapshot, target_image,
                ValidationCommand(
                    f"behavior_target_{index}", case["target_argv"], timeout_seconds=20.0,
                    environment=_command_environment(target_snapshot, case["target_argv"]),
                ),
            )
            executions.extend((source_result, target_result))
            if source_result.status == "TIMEOUT" or target_result.status == "TIMEOUT":
                timed_out = True
                warnings.append(f"Behavior case {case['name']} timed out in the isolated runner.")
                continue
            if source_result.status != "PASSED" or target_result.status != "PASSED":
                if source_result.status == "BLOCKED" or target_result.status == "BLOCKED":
                    blocked = True
                else:
                    failed = True
                warnings.append(f"Behavior case {case['name']} could not produce successful source and target executions.")
                continue
            source_stdout = source_result.stdout.replace("\r\n", "\n")
            target_stdout = target_result.stdout.replace("\r\n", "\n")
            expected = case["expected_stdout"]
            if source_stdout != expected:
                failed = True
                warnings.append(f"Source behavior did not match expected output for case {case['name']}.")
            if target_stdout != expected or target_stdout != source_stdout:
                failed = True
                warnings.append(f"Generated target behavior did not match source/expected output for case {case['name']}.")
        status = "TIMEOUT" if timed_out else "BLOCKED" if blocked else "FAILED" if failed else "PASSED"
        if status == "PASSED":
            warnings.append("Behavior comparison passed only for the explicitly supplied cases; it is not a proof of general semantic equivalence.")
        return BehaviorComparisonResult(status, tuple(executions), tuple(warnings), len(cases))
