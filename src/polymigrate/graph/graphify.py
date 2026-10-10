"""Optional Graphify artifact and CLI-query adapter."""
from __future__ import annotations
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GraphResult:
    status: str
    data: dict[str, Any] | list[Any] | None = None
    warning: str | None = None
    output: str | None = None


class GraphifyAdapter:
    def __init__(self, executable: str = "graphify", timeout: float = 20.0,
                 max_output_chars: int = 20_000) -> None:
        if not executable.strip():
            raise ValueError("Graphify executable name is required")
        if timeout <= 0 or max_output_chars < 1:
            raise ValueError("Graphify timeout and output limit must be positive")
        self.executable = executable
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def load_artifact(self, project_root: Path, artifact_path: Path | None = None) -> GraphResult:
        candidate = artifact_path or project_root / "graphify-out" / "graph.json"
        try:
            project_root.resolve(strict=True)
            resolved_candidate = candidate.resolve(strict=True)
        except OSError:
            return GraphResult("unavailable", warning=f"Graphify artifact not found: {candidate}")
        if not resolved_candidate.is_file():
            return GraphResult("unavailable", warning=f"Graphify artifact is not a file: {candidate}")
        try:
            data = json.loads(resolved_candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return GraphResult("degraded", warning=f"Could not read valid Graphify JSON: {type(exc).__name__}")
        if not isinstance(data, (dict, list)):
            return GraphResult("degraded", warning="Graphify JSON root must be an object or array")
        return GraphResult("available", data=data)

    def query(self, project_root: Path, question: str, artifact_path: Path | None = None) -> GraphResult:
        """Query an existing graph using an argument list (never a shell command)."""
        if not question.strip() or len(question) > 4_000:
            raise ValueError("Graphify query must be non-empty and at most 4000 characters")
        root = project_root.expanduser().resolve(strict=True)
        loaded = self.load_artifact(root, artifact_path)
        if loaded.status != "available":
            return loaded
        candidate = (artifact_path or root / "graphify-out" / "graph.json").resolve(strict=True)
        executable = shutil.which(self.executable)
        if executable is None and Path(self.executable).is_file():
            executable = str(Path(self.executable).resolve())
        if executable is None:
            return GraphResult("unavailable", data=loaded.data, warning="Graphify CLI executable was not found")
        command = [executable, "query", question, "--graph", str(candidate)]
        try:
            completed = subprocess.run(
                command, cwd=str(root), capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return GraphResult("degraded", data=loaded.data, warning="Graphify query timed out")
        except OSError as exc:
            return GraphResult("degraded", data=loaded.data, warning=f"Graphify query could not run ({type(exc).__name__})")
        if completed.returncode != 0:
            return GraphResult("degraded", data=loaded.data,
                               warning=f"Graphify query failed with exit code {completed.returncode}")
        output = completed.stdout.strip()
        if not output:
            return GraphResult("degraded", data=loaded.data, warning="Graphify query returned no context")
        warning = None
        if len(output) > self.max_output_chars:
            output = output[:self.max_output_chars]
            warning = f"Graphify query output was truncated to {self.max_output_chars} characters"
        return GraphResult("available", data=loaded.data, warning=warning, output=output)
