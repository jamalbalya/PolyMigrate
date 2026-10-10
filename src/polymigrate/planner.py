"""Deterministic planning path. Does not execute or modify project code."""
from __future__ import annotations

from pathlib import Path

from polymigrate.graph.graphify import GraphifyAdapter
from polymigrate.languages import LanguageRegistry
from polymigrate.models import MigrationPlan, MigrationRequest

_IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build"}


class PlanningError(ValueError):
    pass


def validate_request(request: MigrationRequest, registry: LanguageRegistry) -> tuple[Path, Path]:
    registry.get(request.source_language)
    registry.get(request.target_language)
    try:
        source = request.source.expanduser().resolve(strict=True)
    except OSError as exc:
        raise PlanningError(f"Source directory does not exist: {request.source}") from exc
    if not source.is_dir():
        raise PlanningError(f"Source path is not a directory: {source}")
    output = request.output.expanduser().resolve(strict=False)
    if output == source or source in output.parents:
        raise PlanningError("Output directory must be outside the source tree")
    if output.exists() and not output.is_dir():
        raise PlanningError(f"Output path exists and is not a directory: {output}")
    return source, output


def inventory_source(source: Path, registry: LanguageRegistry) -> list[str]:
    files: list[str] = []
    known_extensions = {ext for language in registry.all() for ext in language.extensions}
    for path in sorted(source.rglob("*")):
        if not path.is_file() or any(part in _IGNORED_DIRS for part in path.relative_to(source).parts):
            continue
        if path.suffix.lower() in known_extensions:
            files.append(path.relative_to(source).as_posix())
    return files


def create_plan(request: MigrationRequest, registry: LanguageRegistry | None = None,
                graphify: GraphifyAdapter | None = None) -> MigrationPlan:
    registry = registry or LanguageRegistry()
    graphify = graphify or GraphifyAdapter()
    source, output = validate_request(request, registry)
    source_language = registry.get(request.source_language)
    target_language = registry.get(request.target_language)
    source_files = inventory_source(source, registry)
    graph = graphify.load_artifact(source)
    warnings: list[str] = []
    if graph.warning:
        warnings.append(graph.warning)
    warnings.append("This milestone creates a plan only; no code has been migrated or behaviorally verified.")
    unresolved = []
    if source_language.id == target_language.id:
        unresolved.append("Source and target languages are identical; confirm whether this is intended as a refactor-only task.")
    return MigrationPlan(
        schema_version="1.0",
        source=str(source),
        source_language=source_language.id,
        target_language=target_language.id,
        output=str(output),
        source_files=source_files,
        source_file_count=len(source_files),
        graphify_status=graph.status,
        warnings=warnings,
        validation_gates=["target-build", "unit-tests", "integration-tests", "e2e-tests", "behavior-comparison", "security-review"],
        unresolved_items=unresolved,
    )
