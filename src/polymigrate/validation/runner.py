"""Docker-isolated validation runner for generated code; it never pulls images or uses a shell."""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from polymigrate.security.redaction import redact_text

_SHELLS = {"sh", "bash", "zsh", "dash", "ash", "cmd", "powershell", "pwsh"}
_IMAGE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@_+-]{0,254}$")
_MEMORY_LIMIT = re.compile(r"^\d+(?:[kKmMgGtTpP]i?[bB]?)?$")
_CPU_LIMIT = re.compile(r"^\d+(?:\.\d+)?$")

@dataclass(frozen=True)
class ValidationCommand:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: float = 120.0
    mandatory: bool = True
    environment: tuple[tuple[str, str], ...] = ()
    run_as_current_user: bool = False

@dataclass(frozen=True)
class SandboxExecution:
    command_id: str
    status: str
    image: str
    exit_code: int | None
    duration_seconds: float
    stdout: str = ""
    stderr: str = ""
    details: str = ""


def _test_execution_evidence(command: ValidationCommand, stdout: str, stderr: str) -> bool | None:
    """Return True/False when a runner reports test counts, otherwise None."""
    if not command.command_id.startswith(("unit_tests", "integration_tests", "e2e_tests")):
        return None
    output = stdout + "\n" + stderr
    if "unittest" in command.argv:
        match = re.search(r"Ran\s+(\d+)\s+tests?", output, re.IGNORECASE)
        return int(match.group(1)) > 0 if match else None
    if Path(command.argv[0]).name == "go" and "test" in command.argv:
        if re.search(r"--- PASS:", output):
            return True
        if "[no test files]" in output or "no tests to run" in output.lower():
            return False
        return None
    if Path(command.argv[0]).name == "cargo" and "test" in command.argv:
        counts = [int(value) for value in re.findall(r"running\s+(\d+)\s+tests?", output, re.IGNORECASE)]
        return any(value > 0 for value in counts) if counts else None
    if Path(command.argv[0]).name == "mvn" and any(part in {"test", "verify"} for part in command.argv):
        counts = [int(value) for value in re.findall(r"Tests run:\s*(\d+)", output, re.IGNORECASE)]
        return any(value > 0 for value in counts) if counts else None
    if re.search(r"No tests?(?:\s+files?)?\s+(?:were\s+)?found|Tests:\s*0\s+total|Test Suites:\s*0\s+total", output, re.IGNORECASE):
        return False
    if re.search(r"Test Suites:\s*[1-9]\d*|Tests:\s*[1-9]\d*\s|\d+\s+passed\b|[1-9]\d*\s+passing|(?m:^PASS\s)|Passed!\s+-\s+Failed:\s*\d+,\s*Passed:\s*[1-9]\d*", output, re.IGNORECASE):
        return True
    return None

class DockerSandboxRunner:
    """Run allowlisted validation commands in a no-network, restricted Docker container."""
    def __init__(self, docker_executable: str = "docker", *, memory_limit: str = "1g",
                 cpus: str = "2", pids_limit: int = 256, max_output_chars: int = 10_000) -> None:
        if not docker_executable.strip() or not _MEMORY_LIMIT.fullmatch(memory_limit) or not _CPU_LIMIT.fullmatch(cpus):
            raise ValueError("Docker executable and valid memory/CPU limits are required")
        if pids_limit < 1 or max_output_chars < 1:
            raise ValueError("pids_limit and max_output_chars must be positive")
        self.docker_executable = docker_executable
        self.memory_limit = memory_limit
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.max_output_chars = max_output_chars

    def run(self, workspace: Path, image: str, command: ValidationCommand) -> SandboxExecution:
        started = time.monotonic()
        def text_value(value: object) -> str:
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return value if isinstance(value, str) else ""

        def result(status: str, exit_code: int | None = None, stdout: object = "",
                   stderr: object = "", details: str = "") -> SandboxExecution:
            safe_stdout = text_value(stdout)[-self.max_output_chars:]
            safe_stderr = text_value(stderr)[-self.max_output_chars:]
            return SandboxExecution(
                command.command_id, status, image, exit_code, round(time.monotonic() - started, 3),
                redact_text(safe_stdout), redact_text(safe_stderr), details,
            )
        if not command.command_id.strip() or not command.argv:
            raise ValueError("Validation command ID and argv are required")
        if command.timeout_seconds <= 0:
            raise ValueError("Validation command timeout must be positive")
        if any(not isinstance(arg, str) or not arg or "\x00" in arg for arg in command.argv):
            raise ValueError("Validation argv must contain non-empty strings without NUL characters")
        for key, value in command.environment:
            if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", key) or "\x00" in value or "\n" in value:
                raise ValueError("Validation environment contains an invalid key or value")
        executable_name = Path(command.argv[0]).name.lower()
        if executable_name in _SHELLS:
            raise ValueError("Shell commands are not permitted; provide an explicit executable and arguments")
        if not image or not _IMAGE_REF.fullmatch(image):
            raise ValueError("A valid single pre-pulled container image reference is required")
        if "," in str(workspace):
            raise ValueError("Workspace paths containing commas are not supported by the Docker mount syntax")
        if workspace.is_symlink():
            raise ValueError("Validation workspace must not be a symlink")
        try:
            resolved_workspace = workspace.expanduser().resolve(strict=True)
        except OSError:
            return result("BLOCKED", details="Validation workspace does not exist")
        if not resolved_workspace.is_dir():
            return result("BLOCKED", details="Validation workspace is not a directory")
        docker = shutil.which(self.docker_executable)
        if docker is None and Path(self.docker_executable).is_file():
            docker = str(Path(self.docker_executable).resolve())
        if docker is None:
            return result("BLOCKED", details="Docker executable was not found")
        try:
            inspected = subprocess.run(
                [docker, "image", "inspect", image], capture_output=True, text=True,
                timeout=min(command.timeout_seconds, 10.0), check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return result("BLOCKED", details=f"Docker image preflight failed ({type(exc).__name__})")
        if inspected.returncode != 0:
            stderr = (inspected.stderr or "").lower()
            if "cannot connect" in stderr or "daemon" in stderr or "permission denied" in stderr:
                details = "Docker daemon or permissions are unavailable; no image was pulled."
            else:
                details = "Validation image is not available locally or could not be inspected; no image was pulled."
            return result("BLOCKED", details=details)
        container_name = "polymigrate-" + uuid.uuid4().hex
        user_args = (
            ["--user", f"{os.getuid()}:{os.getgid()}"]
            if command.run_as_current_user and hasattr(os, "getuid") and hasattr(os, "getgid")
            else []
        )
        docker_argv = [
            docker, "run", "--rm", "--name", container_name, "--network=none", "--read-only", "--cap-drop=ALL",
            *user_args,
            "--security-opt=no-new-privileges", f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory_limit}", f"--cpus={self.cpus}",
            *[item for key, value in command.environment for item in ("--env", f"{key}={value}")],
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--mount", f"type=bind,src={resolved_workspace},dst=/workspace",
            "--workdir", "/workspace", image, *command.argv,
        ]
        try:
            completed = subprocess.run(
                docker_argv, cwd=str(resolved_workspace), capture_output=True, text=True,
                timeout=command.timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            cleanup_failures = []
            for cleanup_argv in ([docker, "kill", container_name], [docker, "rm", "-f", container_name]):
                try:
                    subprocess.run(cleanup_argv, capture_output=True, text=True, timeout=5.0, check=False)
                except Exception as cleanup_exc:
                    cleanup_failures.append(type(cleanup_exc).__name__)
            detail = "Validation command exceeded its time limit; container cleanup was attempted."
            if cleanup_failures:
                detail += " Cleanup commands could not all be confirmed."
            return result("TIMEOUT", stdout=exc.stdout or "", stderr=exc.stderr or "", details=detail)
        except OSError as exc:
            return result("BLOCKED", details=f"Docker execution failed ({type(exc).__name__})")
        if completed.returncode == 0:
            evidence = _test_execution_evidence(command, completed.stdout, completed.stderr)
            if evidence is False:
                return result("NOT_RUN", 0, completed.stdout, completed.stderr,
                              "Test command exited successfully but reported zero executed tests")
            if evidence is None and command.command_id.startswith(("unit_tests", "integration_tests", "e2e_tests")):
                return result("UNVERIFIED", 0, completed.stdout, completed.stderr,
                              "Test command exited successfully; executed test count could not be independently confirmed")
            detail = "Command completed successfully"
            if evidence is True:
                detail = "Command completed successfully and reported executed tests"
            return result("PASSED", 0, completed.stdout, completed.stderr, detail)
        test_command = command.command_id.startswith(("unit_tests", "integration_tests", "e2e_tests"))
        combined_output = (completed.stdout or "") + "\n" + (completed.stderr or "")
        if test_command and "No module named" in combined_output and "pytest" in combined_output:
            return result("BLOCKED", completed.returncode, completed.stdout, completed.stderr,
                          "pytest is not installed in the validation image; no package installation was attempted")
        if test_command and completed.returncode == 5 and re.search(r"no tests ran|no tests found", combined_output, re.IGNORECASE):
            return result("NOT_RUN", completed.returncode, completed.stdout, completed.stderr,
                          "pytest did not discover any tests")
        return result("FAILED", completed.returncode, completed.stdout, completed.stderr,
                      "Command exited with a non-zero status")
