"""Deterministic ranking for possible library-gap resolution strategies."""
from __future__ import annotations

from polymigrate.models import LibraryCandidate, RankedLibraryCandidate

_VALID_STRATEGIES = {
    "standard_library", "direct_replacement", "composite_solution",
    "compatibility_adapter", "custom_implementation", "architectural_alternative",
}


def rank_candidates(candidates: list[LibraryCandidate]) -> list[RankedLibraryCandidate]:
    """Rank candidates; scores are heuristic, not proof of semantic equivalence."""
    ranked: list[RankedLibraryCandidate] = []
    for candidate in candidates:
        if candidate.strategy not in _VALID_STRATEGIES:
            raise ValueError(f"Unsupported replacement strategy: {candidate.strategy}")
        numeric = (candidate.capability_coverage, candidate.compatibility,
                   candidate.maintenance_score, candidate.security_score,
                   candidate.implementation_cost)
        if any(not 0.0 <= value <= 1.0 for value in numeric):
            raise ValueError("Candidate scores must be between 0.0 and 1.0")
        score = (
            candidate.capability_coverage * 0.35 + candidate.compatibility * 0.30
            + candidate.maintenance_score * 0.10 + candidate.security_score * 0.15
            + (1.0 - candidate.implementation_cost) * 0.10
        )
        verified = bool(candidate.evidence) and all(item.verified for item in candidate.evidence)
        ranked.append(RankedLibraryCandidate(candidate, round(score, 6), verified))
    return sorted(ranked, key=lambda item: (-item.score, item.candidate.name.casefold()))
