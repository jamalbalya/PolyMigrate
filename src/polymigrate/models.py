"""Typed domain models shared by the migration foundation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class MigrationStatus(StrEnum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class Evidence:
    kind: str
    description: str
    verified: bool = False
    source: str | None = None


@dataclass(frozen=True)
class MigrationRequest:
    source: Path
    source_language: str
    target_language: str
    output: Path


@dataclass(frozen=True)
class LibraryCandidate:
    name: str
    strategy: str
    capability_coverage: float
    compatibility: float
    maintenance_score: float = 0.5
    security_score: float = 0.5
    implementation_cost: float = 0.5
    evidence: tuple[Evidence, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class RankedLibraryCandidate:
    candidate: LibraryCandidate
    score: float
    evidence_verified: bool


@dataclass
class MigrationPlan:
    schema_version: str
    source: str
    source_language: str
    target_language: str
    output: str
    source_files: list[str] = field(default_factory=list)
    source_file_count: int = 0
    selected_strategy: str = "analyze-and-plan"
    graphify_status: str = "not-configured"
    warnings: list[str] = field(default_factory=list)
    validation_gates: list[str] = field(default_factory=list)
    unresolved_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    gate: str
    passed: bool
    details: str
    mandatory: bool = True
    evidence: tuple[Evidence, ...] = ()


@dataclass
class FinalReviewSummary:
    status: MigrationStatus
    source: str
    target: str
    validation_results: list[ValidationResult]
    changes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    unverified_assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "source": self.source,
            "target": self.target,
            "validation_results": [asdict(result) for result in self.validation_results],
            "changes": self.changes,
            "risks": self.risks,
            "unverified_assumptions": self.unverified_assumptions,
        }
