"""Evidence-derived final review status."""
from __future__ import annotations

from polymigrate.models import FinalReviewSummary, MigrationStatus, ValidationResult


def build_final_summary(
    source: str,
    target: str,
    validation_results: list[ValidationResult],
    changes: list[str] | None = None,
    risks: list[str] | None = None,
    unverified_assumptions: list[str] | None = None,
) -> FinalReviewSummary:
    mandatory = [result for result in validation_results if result.mandatory]
    if not mandatory:
        status = MigrationStatus.PARTIAL
    elif any(not result.passed for result in mandatory):
        status = MigrationStatus.BLOCKED if all(not result.passed for result in mandatory) else MigrationStatus.PARTIAL
    elif unverified_assumptions or risks:
        status = MigrationStatus.PARTIAL
    else:
        status = MigrationStatus.SUCCESS
    return FinalReviewSummary(
        status=status,
        source=source,
        target=target,
        validation_results=validation_results,
        changes=changes or [],
        risks=risks or [],
        unverified_assumptions=unverified_assumptions or [],
    )
