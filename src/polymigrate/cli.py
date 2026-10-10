"""Command-line interface."""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path

from polymigrate.ai.config import build_provider_registry
from polymigrate.graph.graphify import GraphifyAdapter
from polymigrate.knowledge import KnowledgeRecord, MigrationKnowledgeStore, fingerprint_payload
from polymigrate.languages import LanguageRegistry
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.dependencies import DependencyGapPlanner
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine
from polymigrate.migration.research import LibraryResolutionWorkflow
from polymigrate.models import MigrationRequest
from polymigrate.planner import PlanningError, create_plan
from polymigrate.skills.registry import SkillRegistry
from polymigrate.validation.repair import AutonomousRepairLoop
from polymigrate.validation.suite import validate_generated_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polymigrate", description="Plan cross-language project migrations safely.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Analyze a source project and write a migration plan")
    plan.add_argument("--source", required=True, type=Path, help="Source project directory")
    plan.add_argument("--from", dest="source_language", required=True, help="Source language ID")
    plan.add_argument("--to", dest="target_language", required=True, help="Target language ID")
    plan.add_argument("--output", required=True, type=Path, help="Output directory")
    plan.add_argument("--json", dest="json_path", type=Path, help="Optional path for a copy of the plan JSON")
    subparsers.add_parser("providers", help="Show configured AI providers without making network requests")
    migrate = subparsers.add_parser("migrate", help="Experimental AI file translation; output remains unverified")
    migrate.add_argument("--source", required=True, type=Path, help="Source project directory")
    migrate.add_argument("--from", dest="source_language", required=True, help="Source language ID")
    migrate.add_argument("--to", dest="target_language", required=True, help="Target language ID")
    migrate.add_argument("--output", required=True, type=Path, help="New or empty output directory outside source")
    migrate.add_argument("--provider", required=True, help="Configured provider ID, e.g. openai, anthropic, gemini, openrouter")
    migrate.add_argument("--allow-source-upload", action="store_true",
                         help="Explicitly allow source code to be sent to the configured external AI provider")
    migrate.add_argument("--context-json", type=Path, help="Optional JSON object with non-secret migration constraints")
    return parser


def _library_resolution_summary(result) -> dict[str, object]:
    decision = result.decision
    selected = next((candidate for candidate in result.candidates
                     if f"{candidate.registry}:{candidate.name}" == decision.candidate_name), None)
    selected_package = None
    if selected is not None:
        selected_package = {
            "name": selected.name, "registry": selected.registry, "version": selected.version,
            "url": selected.url, "license": selected.license, "description": selected.description,
        }
    if decision.decision_type == "candidate" and any(
        candidate.registry == "github-repositories" and f"{candidate.registry}:{candidate.name}" == decision.candidate_name
        for candidate in result.candidates
    ):
        implementation_status = "REFERENCE_REPOSITORY_ONLY"
    else:
        implementation_status = {
            "candidate": "CANDIDATE_IDENTIFIED_NOT_WIRED",
            "custom_implementation": "CUSTOM_IMPLEMENTATION_RECOMMENDED",
            "architectural_alternative": "ARCHITECTURE_CHANGE_RECOMMENDED",
        }.get(decision.decision_type, "UNRESOLVED")
    return {
        "source_library": decision.candidate_name if decision.decision_type == "candidate" else None,
        "decision_type": decision.decision_type, "implementation_status": implementation_status,
        "candidate_name": decision.candidate_name,
        "strategy": decision.strategy, "rationale": decision.rationale,
        "assumptions": list(decision.assumptions), "validation_tests": list(decision.validation_tests),
        "selected_package": selected_package, "warnings": list(result.warnings),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "providers":
        registry, warnings = build_provider_registry()
        configured = registry.all()
        if configured:
            print("Configured AI providers:")
            for provider in configured:
                capabilities = provider.get_capabilities()
                model = getattr(provider, "model_id", "unknown")
                print(f"- {provider.provider_id}: model={model}, structured_output={capabilities.structured_output}, tool_calling={capabilities.tool_calling}")
        else:
            print("No AI providers configured. Set a provider API key and model ID in environment variables.")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0
    if args.command == "migrate":
        try:
            if not args.allow_source_upload:
                raise PermissionError("Source upload is disabled; pass --allow-source-upload to enable external AI analysis")
            language_registry = LanguageRegistry()
            source_language = language_registry.get(args.source_language)
            target_language = language_registry.get(args.target_language)
            context = {}
            if args.context_json:
                context = json.loads(args.context_json.read_text(encoding="utf-8"))
                if not isinstance(context, dict):
                    raise ValueError("context JSON must contain an object")
            builtin_skill_root = Path(__file__).resolve().parent / "skills" / "builtin"
            migration_skills = SkillRegistry().load_directory(builtin_skill_root)
            context["migration_skills"] = [
                {"id": skill.id, "version": skill.version, "description": skill.description,
                 "instructions": skill.instructions}
                for skill in migration_skills
            ]
            graph = GraphifyAdapter().query(
                args.source,
                f"Summarize the project architecture, important dependencies, and call relationships relevant to migrating from {source_language.id} to {target_language.id}. Identify likely high-impact modules and uncertainty.",
            )
            context["graphify_status"] = graph.status
            if graph.output:
                context["graphify_context"] = graph.output
            if graph.warning:
                context["graphify_warning"] = graph.warning

            providers, _provider_warnings = build_provider_registry()
            source_adapter = InventorySourceAdapter(source_language.id, source_language.extensions)
            source_project = source_adapter.analyze(args.source)
            project_scope = fingerprint_payload({
                "project_root": str(args.source.expanduser().resolve()),
                "source_files": [{"path": unit.relative_path, "sha256": unit.content_sha256} for unit in source_project.units],
            }) if knowledge_store else None
            dependency_warnings: list[str] = []
            resolution_warnings: list[str] = []
            dependency_inventory: list[str] = []
            library_resolutions: list[dict[str, object]] = []
            try:
                gap_plan = DependencyGapPlanner(providers).plan(
                    args.provider, source_project, target_language.id, graph.output, max_gaps=3,
                )
                dependency_inventory = list(gap_plan.observed_dependencies)
                dependency_warnings.extend(gap_plan.warnings)
                resolution_workflow = LibraryResolutionWorkflow(providers)
                for gap in gap_plan.gaps:
                    try:
                        resolution = resolution_workflow.resolve(
                            args.provider, source_library=gap.source_library,
                            target_language=target_language.id,
                            required_capabilities=list(gap.required_capabilities),
                            max_queries=3, results_per_query=5,
                        )
                        summary = _library_resolution_summary(resolution)
                        summary["source_library"] = gap.source_library
                        summary["required_capabilities"] = list(gap.required_capabilities)
                        summary["reason"] = gap.reason
                        summary["evidence_files"] = list(gap.evidence_files)
                        library_resolutions.append(summary)
                        resolution_warnings.extend(resolution.warnings)
                    except (ValueError, RuntimeError, OSError) as exc:
                        warning = f"Library resolution failed for {gap.source_library} ({type(exc).__name__}); translation will proceed with an explicit warning."
                        resolution_warnings.append(warning)
                        library_resolutions.append({
                            "source_library": gap.source_library, "decision_type": "unresolved",
                            "strategy": "unresolved", "reason": gap.reason, "warnings": [warning],
                        })
            except (ValueError, RuntimeError, OSError) as exc:
                dependency_warnings.append(
                    f"Dependency gap planning failed ({type(exc).__name__}); translation will continue without verified library decisions."
                )
            context["dependency_inventory"] = dependency_inventory
            context["library_resolution"] = library_resolutions
            context["dependency_planning_warnings"] = dependency_warnings
            context["library_resolution_warnings"] = resolution_warnings

            knowledge_db = os.environ.get("POLYMIGRATE_KNOWLEDGE_DB", "").strip()
            cache_drafts = os.environ.get("POLYMIGRATE_CACHE_DRAFTS", "").strip().lower() in {"1", "true", "yes"}
            if cache_drafts and not knowledge_db:
                raise ValueError("POLYMIGRATE_CACHE_DRAFTS requires POLYMIGRATE_KNOWLEDGE_DB")
            knowledge_store = MigrationKnowledgeStore(Path(knowledge_db).expanduser()) if knowledge_db else None
            project_scope = fingerprint_payload({"project_root": str(args.source.expanduser().resolve())}) if knowledge_store else None
            adapters = AdapterRegistry()
            adapters.register_source(source_adapter)
            target_adapter = LLMTargetAdapter(
                target_language.id, source_language.id, target_language.extensions[0],
                providers, args.provider, allow_source_upload=args.allow_source_upload,
                target_extensions=target_language.extensions, knowledge_store=knowledge_store,
                project_scope=project_scope, cache_drafts=cache_drafts,
            )
            adapters.register_target(target_adapter)
            result = MigrationEngine(adapters).execute(
                args.source, source_language.id, target_language.id, args.output, context,
                source_project=source_project,
            )
            image_variable = f"POLYMIGRATE_DOCKER_IMAGE_{target_language.id.upper()}"
            validation_image = os.environ.get(image_variable, "").strip() or None
            initial_validation = validate_generated_project(result.output_root, target_language.id, validation_image)
            repair_result = AutonomousRepairLoop(
                providers, args.provider, target_language.id, target_language.extensions,
            ).run(result.output_root, validation_image, context, initial_validation=initial_validation)
            validation = repair_result.validation
            gates = validation.gates
            all_warnings = list(result.warnings) + list(validation.warnings) + list(repair_result.warnings)
            failed_gates = {"FAILED", "BLOCKED", "TIMEOUT"}
            if any(value in failed_gates for value in gates.values()):
                overall_status = "BLOCKED"
            elif any(value == "PASSED" for value in gates.values()) and any(
                value == "NOT_RUN" for value in gates.values()
            ):
                overall_status = "PARTIAL"
            else:
                overall_status = "GENERATED_UNVERIFIED"
            summary = {
                "status": overall_status, "source_language": result.source_language,
                "target_language": result.target_language, "generated_files": list(result.generated_files),
                "dependency_inventory": dependency_inventory, "library_resolution": library_resolutions,
                "warnings": all_warnings, "validation_image": validation_image,
                "repair": repair_result.to_dict(),
                "validation_gates": gates, "validation_results": validation.to_dict(),
                "note": "Experimental per-file translation with bounded AI repair; dependency manifests and full-project behavior are not guaranteed.",
            }
            report_path = result.output_root / "migration-review.json"
            report_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 3 if overall_status == "BLOCKED" else 0
        except (PlanningError, ValueError, OSError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    try:
        request = MigrationRequest(args.source, args.source_language, args.target_language, args.output)
        plan = create_plan(request)
        payload = json.dumps(plan.to_dict(), indent=2, sort_keys=True) + "\n"
        plan_path = args.json_path or (args.output / "migration-plan.json")
        plan_path = plan_path.expanduser().resolve(strict=False)
        if plan_path == Path(plan.source) or Path(plan.source) in plan_path.parents:
            raise PlanningError("Plan JSON path must be outside the source tree")
        args.output.mkdir(parents=True, exist_ok=True)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(payload, encoding="utf-8")
        print(payload, end="")
        print(f"Plan written to: {plan_path}", file=sys.stderr)
        return 0
    except (PlanningError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
