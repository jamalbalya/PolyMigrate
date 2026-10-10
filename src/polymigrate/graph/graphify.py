"""Conservative Graphify artifact reader; does not assume a particular schema."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GraphResult:
    status: str
    data: dict[str, Any] | list[Any] | None = None
    warning: str | None = None


class GraphifyAdapter:
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
            raw = resolved_candidate.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return GraphResult("degraded", warning=f"Could not read valid Graphify JSON: {type(exc).__name__}")
        if not isinstance(data, (dict, list)):
            return GraphResult("degraded", warning="Graphify JSON root must be an object or array")
        return GraphResult("available", data=data)
