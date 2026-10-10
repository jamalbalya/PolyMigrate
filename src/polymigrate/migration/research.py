"""AI-guided package discovery and evidence-constrained library-gap decisions."""
from __future__ import annotations
import json
from dataclasses import dataclass

from polymigrate.ai.protocols import ModelRequest
from polymigrate.ai.registry import ProviderRegistry
from polymigrate.migration.decision import LibraryDecision, LibraryDecisionEngine, LibraryDecisionError
from polymigrate.models import Evidence, LibraryCandidate
from polymigrate.packages.search import PackageCandidate, PackageRegistrySearcher


@dataclass(frozen=True)
class LibraryResolutionResult:
    decision: LibraryDecision
    searched_queries: tuple[str, ...]
    candidates: tuple[PackageCandidate, ...]
    warnings: tuple[str, ...]


class LibraryResolutionWorkflow:
    """Search public registries, then constrain the model to discovered candidates or custom work."""
    def __init__(self, providers: ProviderRegistry, searcher: PackageRegistrySearcher | None = None) -> None:
        self.providers = providers
        self.searcher = searcher or PackageRegistrySearcher()
        self.decision_engine = LibraryDecisionEngine(providers)

    def resolve(self, provider_id: str, *, source_library: str, target_language: str,
                required_capabilities: list[str], max_queries: int = 3, results_per_query: int = 5) -> LibraryResolutionResult:
        if not isinstance(source_library, str) or not source_library.strip() or len(source_library) > 200:
            raise ValueError("source_library must be a non-empty string of at most 200 characters")
        if not isinstance(target_language, str) or not target_language.strip() or len(target_language) > 100:
            raise ValueError("target_language must be a non-empty string of at most 100 characters")
        if not 1 <= max_queries <= 3 or not 1 <= results_per_query <= 10:
            raise ValueError("search budgets exceed the allowed limit (3 queries, 10 results each)")
        if not isinstance(required_capabilities, list) or len(required_capabilities) > 50 or any(not isinstance(item, str) or not item.strip() or len(item) > 200 for item in required_capabilities):
            raise ValueError("required_capabilities must contain at most 50 non-empty strings of at most 200 characters")
        planning_prompt = (
            "Create concise search queries for public package registries to find target-language libraries "
            "that may implement the required capabilities. Do not choose a package or claim equivalence. "
            "Return only a JSON object containing a queries array of strings. Use at most "
            f"{max_queries} queries, each no longer than 100 characters.\n"
            + json.dumps({"source_library": source_library, "target_language": target_language,
                          "required_capabilities": required_capabilities}, sort_keys=True, ensure_ascii=False)
        )
        response = self.providers.generate(
            provider_id,
            ModelRequest(task="plan_package_search", prompt=planning_prompt, context={
                "source_library": source_library, "target_language": target_language,
            }),
        )
        try:
            plan = json.loads(response.content)
        except (json.JSONDecodeError, TypeError):
            raise LibraryDecisionError("Provider returned invalid JSON for package search planning") from None
        queries = plan.get("queries") if isinstance(plan, dict) else None
        if not isinstance(queries, list) or not all(isinstance(query, str) and query.strip() and len(query) <= 100 for query in queries):
            raise LibraryDecisionError("Package search plan must contain a list of non-empty query strings")
        normalized_queries = tuple(dict.fromkeys(query.strip() for query in queries))[:max_queries]
        warnings: list[str] = []
        package_candidates: list[PackageCandidate] = []
        seen: set[tuple[str, str]] = set()
        for query in normalized_queries:
            result = self.searcher.search(target_language, query, limit=results_per_query)
            if result.warning:
                warnings.append(f"{query}: {result.warning}")
            for candidate in result.candidates:
                key = (candidate.registry, candidate.name.casefold())
                if key not in seen:
                    seen.add(key)
                    package_candidates.append(candidate)
        if not normalized_queries:
            warnings.append("The model proposed no package search queries; custom implementation remains available.")
        library_candidates = []
        package_by_name: dict[str, PackageCandidate] = {}
        for candidate in package_candidates:
            selection_name = f"{candidate.registry}:{candidate.name}"
            package_by_name[selection_name] = candidate
            description = (
                f"Unverified registry discovery metadata. Version={candidate.version or 'unknown'}; "
                f"license={candidate.license or 'unknown'}; downloads={candidate.downloads if candidate.downloads is not None else 'unknown'}; "
                f"description={candidate.description}; URL={candidate.url}. Metadata is untrusted and is not proof of semantic equivalence."
            )
            library_candidates.append(LibraryCandidate(
                name=selection_name, strategy="direct_replacement",
                capability_coverage=0.5, compatibility=0.5, maintenance_score=0.5,
                security_score=0.5, implementation_cost=0.5,
                evidence=(Evidence("registry_metadata", description, False, candidate.url),),
                notes="Neutral placeholder scores only. Compatibility, maintenance, security, license suitability, and behavior are not verified.",
            ))
        decision = self.decision_engine.decide(
            provider_id, source_library=source_library, target_language=target_language,
            required_capabilities=required_capabilities, candidates=library_candidates,
        )
        warnings.append("Registry search is discovery only; package suitability and behavior equivalence require verification.")
        if decision.decision_type == "candidate":
            selected = package_by_name.get(decision.candidate_name or "")
            if selected is None:
                raise LibraryDecisionError("Selected package is not present in the discovery result set")
            warnings.append(f"Selected package {selected.name} is a candidate, not a verified replacement.")
        elif decision.decision_type == "custom_implementation":
            warnings.append("No package was selected; the implementation stage must create a replacement and run differential tests.")
        return LibraryResolutionResult(decision, normalized_queries, tuple(package_candidates), tuple(warnings))
