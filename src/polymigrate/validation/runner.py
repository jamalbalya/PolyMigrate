"""Docker-isolated validation runner for generated code; it never pulls images or uses a shell."""
from __future__ import annotations
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from polymigrate.security.redaction import redact_text

_SHELLS = {"sh", "bash", "zsh", "dash", "ash", "cmd", "powershell", "pwsh"}

@dataclass(frozen=True)
class ValidationCommand:
    command_id: str
    argv: tuple[str, ...]
    timeout_seconds: float = 120.0
    mandatory: bool = True
    environment: tuple[tuple[str, str], ...] = ()

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

class DockerSandboxRunner:
    """Run allowlisted validation commands in a no-network, restricted Docker container."""
    def __init__(self, docker_executable: str = "docker", *, memory_limit: str = "1g",
                 cpus: str = "2", pids_limit: int = 256, max_output_chars: int = 10_000) -> None:
        if not docker_executable.strip() or not memory_limit.strip() or not cpus.strip():
            raise ValueError("Docker executable and resource limits are required")
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
        executable_name = Path(command.argv[0]).name.lower()
        if executable_name in _SHELLS:
            raise ValueError("Shell commands are not permitted; provide an explicit executable and arguments")
        if not image or any(ch.isspace() for ch in image):
            raise ValueError("A single pre-pulled container image reference is required")
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
            return result("BLOCKED", details="Validation image is not available locally; no image was pulled")
        docker_argv = [
            docker, "run", "--rm", "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", f"--pids-limit={self.pids_limit}",
            f"--memory={self.memory_limit}", f"--cpus={self.cpus}",
            *[item for key, value in command.environment for item in ("--env", f"{key}={value}")],
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--mount", f"type=bind,src={resolved_workspace},dst=/workspace,rw",
            "--workdir", "/workspace", image, *command.argv,
        ]
        try:
            completed = subprocess.run(
                docker_argv, cwd=str(resolved_workspace), capture_output=True, text=True,
                timeout=command.timeout_seconds, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return result("TIMEOUT", stdout=exc.stdout or "", stderr=exc.stderr or "",
                          details="Validation command exceeded its time limit")
        except OSError as exc:
            return result("BLOCKED", details=f"Docker execution failed ({type(exc).__name__})")
        if completed.returncode == 0:
            return result("PASSED", 0, completed.stdout, completed.stderr, "Command completed successfully")
        return result("FAILED", completed.returncode, completed.stdout, completed.stderr,
                      "Command exited with a non-zero status")
