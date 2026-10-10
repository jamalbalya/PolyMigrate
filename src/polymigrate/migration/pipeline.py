"""Adapter contracts and safe output writer for pluggable migration pipelines."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

@dataclass(frozen=True)
class SourceUnit:
    relative_path: str
    source_text: str
    content_sha256: str
    symbols: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

@dataclass(frozen=True)
class SourceProject:
    source_root: Path
    language_id: str
    units: tuple[SourceUnit, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class GeneratedArtifact:
    relative_path: str
    content: str

@dataclass(frozen=True)
class MigrationExecutionResult:
    status: str
    source_language: str
    target_language: str
    output_root: Path
    generated_files: tuple[str, ...]
    warnings: tuple[str, ...]

class SourceAdapter(Protocol):
    language_id: str
    def analyze(self, source_root: Path) -> SourceProject: ...

class TargetAdapter(Protocol):
    language_id: str
    def generate(self, project: SourceProject, context: dict[str, Any]) -> list[GeneratedArtifact]: ...

class AdapterRegistry:
    """Keeps source analyzers and target generators independently extensible."""
    def __init__(self) -> None:
        self._sources: dict[str, SourceAdapter] = {}
        self._targets: dict[str, TargetAdapter] = {}

    def register_source(self, adapter: SourceAdapter) -> None:
        self._register(self._sources, adapter.language_id, adapter, "source")

    def register_target(self, adapter: TargetAdapter) -> None:
        self._register(self._targets, adapter.language_id, adapter, "target")

    @staticmethod
    def _register(registry: dict[str, Any], language_id: str, adapter: Any, kind: str) -> None:
        if not language_id or language_id.strip().lower() != language_id:
            raise ValueError(f"{kind} adapter language_id must be canonical lowercase text")
        if language_id in registry:
            raise ValueError(f"{kind.title()} adapter already registered for {language_id}")
        registry[language_id] = adapter

    def source(self, language_id: str) -> SourceAdapter:
        try:
            return self._sources[language_id]
        except KeyError as exc:
            raise ValueError(f"No source adapter registered for {language_id}") from exc

    def target(self, language_id: str) -> TargetAdapter:
        try:
            return self._targets[language_id]
        except KeyError as exc:
            raise ValueError(f"No target adapter registered for {language_id}") from exc

class MigrationEngine:
    """Run registered adapters and write generated files without touching source."""
    def __init__(self, adapters: AdapterRegistry, *, max_generated_files: int = 10_000,
                 max_artifact_bytes: int = 10 * 1024 * 1024) -> None:
        if max_generated_files < 1 or max_artifact_bytes < 1:
            raise ValueError("output limits must be positive")
        self.adapters = adapters
        self.max_generated_files = max_generated_files
        self.max_artifact_bytes = max_artifact_bytes

    def execute(self, source_root: Path, source_language: str, target_language: str,
                output_root: Path, context: dict[str, Any] | None = None) -> MigrationExecutionResult:
        source = source_root.expanduser().resolve(strict=True)
        if not source.is_dir():
            raise ValueError("Source root must be a directory")
        if output_root.is_symlink():
            raise ValueError("Output root must not be a symlink")
        output = output_root.expanduser().resolve(strict=False)
        if output == source or source in output.parents:
            raise ValueError("Output directory must be outside the source tree")
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("Output directory must be absent or empty")
        source_adapter = self.adapters.source(source_language)
        target_adapter = self.adapters.target(target_language)
        project = source_adapter.analyze(source)
        if project.language_id != source_language:
            raise ValueError("Source adapter returned a project with a mismatched language ID")
        seen: set[str] = set()
        for unit in project.units:
            relative = PurePosixPath(unit.relative_path)
            if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                raise ValueError("Source adapter returned an unsafe relative path")
            if unit.relative_path in seen:
                raise ValueError("Source adapter returned duplicate unit paths")
            seen.add(unit.relative_path)
            expected = hashlib.sha256(unit.source_text.encode("utf-8")).hexdigest()
            if unit.content_sha256 != expected:
                raise ValueError(f"Source adapter returned an invalid content hash for {unit.relative_path}")
        artifacts = target_adapter.generate(project, context or {})
        if len(artifacts) > self.max_generated_files:
            raise ValueError("Target adapter exceeded the generated file limit")
        for artifact in artifacts:
            if not isinstance(artifact.content, str):
                raise ValueError("Target adapter content must be text")
            if len(artifact.content.encode("utf-8")) > self.max_artifact_bytes:
                raise ValueError(f"Target artifact exceeds size limit: {artifact.relative_path}")
        output.mkdir(parents=True, exist_ok=True)
        written: list[str] = []
        artifact_paths: set[str] = set()
        root_resolved = output.resolve(strict=True)
        for artifact in artifacts:
            relative = PurePosixPath(artifact.relative_path)
            if (relative.is_absolute() or ".." in relative.parts or not relative.parts
                    or "\\" in artifact.relative_path or "\x00" in artifact.relative_path
                    or ":" in relative.parts[0]):
                raise ValueError(f"Target adapter returned unsafe output path: {artifact.relative_path}")
            normalized = relative.as_posix()
            if normalized in artifact_paths:
                raise ValueError(f"Target adapter returned duplicate output path: {normalized}")
            artifact_paths.add(normalized)
            destination = output.joinpath(*relative.parts)
            # Reject existing symlink components and any path that resolves outside output.
            cursor = output
            for part in relative.parts[:-1]:
                cursor = cursor / part
                if cursor.is_symlink():
                    raise ValueError(f"Output path traverses a symlink: {normalized}")
            resolved_destination = destination.resolve(strict=False)
            if root_resolved not in resolved_destination.parents:
                raise ValueError(f"Output path escapes output directory: {normalized}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise ValueError(f"Target adapter would overwrite an existing file: {normalized}")
            destination.write_text(artifact.content, encoding="utf-8")
            written.append(normalized)
        return MigrationExecutionResult(
            status="GENERATED_UNVERIFIED", source_language=source_language,
            target_language=target_language, output_root=output,
            generated_files=tuple(sorted(written)),
            warnings=("Generated output has not yet passed build, test, security, or behavior-equivalence gates.",),
        )
