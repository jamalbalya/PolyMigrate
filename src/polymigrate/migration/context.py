"""Bounded parser-derived context shared with AI translation prompts."""
from __future__ import annotations

import json
from typing import Any

from polymigrate.migration.pipeline import SourceProject


def build_source_project_index(
    project: SourceProject,
    *,
    max_files: int = 100,
    max_symbols_per_file: int = 12,
    max_dependencies_per_file: int = 12,
    max_context_chars: int = 50_000,
) -> dict[str, Any]:
    """Create a deterministic, content-free project index with a strict prompt-size cap."""
    if min(max_files, max_symbols_per_file, max_dependencies_per_file) < 1:
        raise ValueError("Project index limits must be positive")
    if max_context_chars < 512:
        raise ValueError("max_context_chars must be at least 512")

    units = sorted(project.units, key=lambda unit: unit.relative_path)
    entries: list[dict[str, Any]] = []
    for unit in units[:max_files]:
        entries.append({
            "path": unit.relative_path[:300],
            "sha256": unit.content_sha256[:64],
            "symbols": [item[:120] for item in unit.symbols[:max_symbols_per_file]],
            "dependencies": [item[:120] for item in unit.dependencies[:max_dependencies_per_file]],
        })

    parser_backends = project.metadata.get("parser_backends", [])
    if not isinstance(parser_backends, list):
        parser_backends = []
    payload: dict[str, Any] = {
        "schema_version": 1,
        "source_language": project.language_id[:80],
        "total_source_files": len(units),
        "included_file_count": len(entries),
        "omitted_file_count": max(0, len(units) - len(entries)),
        "truncated": len(units) > len(entries),
        "parser_backends": [item[:80] for item in parser_backends[:20] if isinstance(item, str)],
        "files": entries,
    }

    # Drop trailing entries deterministically until the entire JSON payload fits.
    while entries and len(json.dumps(payload, sort_keys=True, ensure_ascii=False)) > max_context_chars:
        entries.pop()
        payload["included_file_count"] = len(entries)
        payload["omitted_file_count"] = len(units) - len(entries)
        payload["truncated"] = True
        payload["files"] = entries
    if len(json.dumps(payload, sort_keys=True, ensure_ascii=False)) > max_context_chars:
        # The metadata header is small, but enforce the cap even with unusual input.
        payload["parser_backends"] = []
        payload["files"] = []
        payload["included_file_count"] = 0
        payload["omitted_file_count"] = len(units)
        payload["truncated"] = bool(units)
    return payload
