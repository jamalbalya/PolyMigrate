"""Command-line interface."""
from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from polymigrate.ai.config import build_provider_registry
from polymigrate.ai.protocols import ModelRequest
from polymigrate.graph.graphify import GraphifyAdapter
from polymigrate.knowledge import KnowledgeRecord, MigrationKnowledgeStore, fingerprint_payload
from polymigrate.languages import LanguageRegistry
from polymigrate.migration.adapters import InventorySourceAdapter
from polymigrate.migration.dependencies import DependencyGapPlanner
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.manifests import scan_project_manifests
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine
from polymigrate.migration.python_go_target import PythonToGoTargetAdapter
from polymigrate.migration.research import LibraryResolutionWorkflow
from polymigrate.models import MigrationRequest
from polymigrate.planner import PlanningError, create_plan
from polymigrate.skills.registry import SkillRegistry
from polymigrate.validation.repair import AutonomousRepairLoop
from polymigrate.validation.suite import validate_generated_project
from polymigrate.validation.behavior import compare_behavior
from polymigrate.validation.dependency_wiring import review_dependency_wiring
from polymigrate.security.static_review import review_generated_output
from polymigrate.security.evidence_gate import evaluate_security_evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polymigrate", description="Plan cross-language project migrations safely.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Analyze a source project and write a migration plan")
    plan.add_argument("--source", required=True, type=Path, help="Source project directory")
    plan.add_argument("--from", dest="source_language", required=True, help="Source language ID")
    plan.add_argument("--to", dest="target_language", required=True, help="Target language ID")
    plan.add_argument("--output", required=True, type=Path, help="Output directory")
    plan.add_argument("--json", dest="json_path", type=Path, help="Optional path for a copy of the plan JSON")
    providers = subparsers.add_parser("providers", help="Show configured AI providers without making network requests")
    providers.add_argument("--check", action="store_true", help="Send a minimal, source-free live request to each configured provider")
    providers.add_argument("--list-models", action="store_true", help="Query model IDs from configured OpenAI-compatible providers")
    migrate = subparsers.add_parser("migrate", help="Experimental AI file translation; output remains unverified")
    migrate.add_argument("--source", required=True, type=Path, help="Source project directory")
    migrate.add_argument("--from", dest="source_language", required=True, help="Source language ID")
    migrate.add_argument("--to", dest="target_language", required=True, help="Target language ID")
    migrate.add_argument("--output", required=True, type=Path, help="New or empty output directory outside source")
    migrate.add_argument("--strategy", choices=("llm", "deterministic"), default="llm", help="Translation strategy (default: llm)")
    migrate.add_argument("--provider", required=False, help="Configured provider ID, e.g. openai, anthropic, gemini, openrouter")
    migrate.add_argument("--allow-source-upload", action="store_true",
                         help="Explicitly allow source code to be sent to the configured external AI provider")
    migrate.add_argument("--context-json", type=Path, help="Optional JSON object with non-secret migration constraints")
    migrate.add_argument("--behavior-spec", type=Path, help="JSON behavior contract for isolated source-vs-target output comparison")
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




def _derive_final_status(
    gates: dict[str, str],
    *,
    security_status: str,
    dependency_status: str,
    required_gates: set[str],
) -> str:
    """Derive the public final status from validation evidence."""
    failed = {"FAILED", "BLOCKED", "TIMEOUT", "INCOMPLETE"}

    if (
        security_status in {"FAILED", "BLOCKED", "INCOMPLETE", "REVIEW_REQUIRED"}
        or dependency_status in {"BLOCKED", "UNVERIFIED"}
        or any(gates.get(name, "NOT_RUN") in failed for name in required_gates)
    ):
        return "BLOCKED"

    if (
        not required_gates
        or any(gates.get(name, "NOT_RUN") != "PASSED" for name in required_gates)
        or security_status != "PASSED"
        or dependency_status != "PASSED"
    ):
        return "PARTIAL"

    return "SUCCESS"

def _run_deterministic_migration(args, source_language, target_language) -> int:
    """Run the offline Python-to-Go subset translator and local Go checks."""
    if (source_language.id, target_language.id) != ("python", "go"):
        raise ValueError(
            "The deterministic strategy currently supports only --from python --to go"
        )

    context = {}
    if args.context_json:
        context = json.loads(args.context_json.read_text(encoding="utf-8"))
        if not isinstance(context, dict):
            raise ValueError("context JSON must contain an object")

    source_adapter = InventorySourceAdapter(
        source_language.id, source_language.extensions
    )
    source_project = source_adapter.analyze(args.source)

    adapters = AdapterRegistry()
    adapters.register_source(source_adapter)
    adapters.register_target(PythonToGoTargetAdapter())
    result = MigrationEngine(adapters).execute(
        args.source,
        source_language.id,
        target_language.id,
        args.output,
        context,
        source_project=source_project,
    )

    # The pipeline and adapter warnings describe the pre-validation state.
    # Do not carry those stale generic messages into the final deterministic
    # report; the validation gates and remaining warnings report actual results.
    stale_validation_warnings = {
        "Generated output has not yet passed build, test, security, or behavior-equivalence gates.",
        "Generated output must pass build, test, security, and behavior checks.",
    }
    warnings = [
        warning for warning in result.warnings
        if warning not in stale_validation_warnings
    ]
    gates = {
        "target_build": "NOT_RUN",
        "go_vet": "NOT_RUN",
        "unit_tests": "NOT_RUN",
        "integration_tests": "NOT_RUN",
        "e2e_tests": "NOT_RUN",
        "behavior_comparison": "NOT_RUN",
        "security_review": "NOT_RUN",
    }
    executions = []

    def run_check(command_id: str, command: list[str], timeout: int = 60):
        started = time.monotonic()
        env = os.environ.copy()
        env.update({
            "GOTOOLCHAIN": "local",
            "GOPROXY": "off",
            "GO111MODULE": "off",
        })
        try:
            completed = subprocess.run(
                command,
                cwd=result.output_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            status = "PASSED" if completed.returncode == 0 else "FAILED"
            record = {
                "command_id": command_id,
                "status": status,
                "exit_code": completed.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout": completed.stdout[-12000:],
                "stderr": completed.stderr[-12000:],
            }
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
            record = {
                "command_id": command_id,
                "status": status,
                "exit_code": None,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout": "",
                "stderr": "Local Go validation exceeded its timeout.",
            }
        except OSError as exc:
            status = "BLOCKED"
            record = {
                "command_id": command_id,
                "status": status,
                "exit_code": None,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout": "",
                "stderr": f"Could not run validation ({type(exc).__name__}).",
            }
        executions.append(record)
        return status

    go = shutil.which("go")
    gofmt = shutil.which("gofmt")
    main_go = result.output_root / "main.go"

    if not go or not gofmt:
        gates["target_build"] = "BLOCKED"
        warnings.append(
            "Go validation is blocked because both go and gofmt must be available."
        )
    else:
        format_status = run_check("gofmt", [gofmt, "-w", str(main_go)])
        if format_status == "PASSED":
            # Keep the build artifact isolated and guarantee cleanup.
            with tempfile.TemporaryDirectory(prefix="polymigrate-go-build-") as build_dir:
                binary_path = str(Path(build_dir) / "program")
                build_status = run_check(
                    "target_build", [go, "build", "-o", binary_path, "main.go"]
                )
                gates["target_build"] = build_status
                if build_status == "PASSED":
                    gates["go_vet"] = run_check("go_vet", [go, "vet", "main.go"])
                else:
                    warnings.append(
                        "go vet was not run because the Go build did not pass."
                    )
        else:
            gates["target_build"] = format_status
            warnings.append("Go formatting failed; build and vet were not run.")

    security_result = review_generated_output(result.output_root)
    dependency_result = review_dependency_wiring(result.output_root, "go")

    # External scanner evidence is an independent gate. Static heuristics alone
    # must never be promoted to a comprehensive security review.
    required_scanners = [
        item.strip()
        for item in os.environ.get("POLYMIGRATE_REQUIRED_SECURITY_SCANNERS", "").split(",")
        if item.strip()
    ]
    evidence_items = []
    evidence_path_value = os.environ.get("POLYMIGRATE_SECURITY_EVIDENCE_JSON", "").strip()
    evidence_load_error = None
    if evidence_path_value:
        evidence_path = Path(evidence_path_value)
        try:
            loaded_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            if isinstance(loaded_evidence, dict):
                loaded_evidence = loaded_evidence.get("scanners")
            if not isinstance(loaded_evidence, list):
                raise ValueError("evidence JSON must be a list or an object containing a scanners list")
            evidence_items = loaded_evidence
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            evidence_load_error = f"Could not load scanner evidence ({type(exc).__name__})."

    security_evidence_result = evaluate_security_evidence(
        evidence_items,
        required_scanners=required_scanners,
    )
    security_evidence_report = security_evidence_result.to_dict()
    if evidence_load_error:
        security_evidence_report["status"] = "INCOMPLETE"
        security_evidence_report["errors"].append(evidence_load_error)
    static_security_status = security_result.status
    combined_security_status = static_security_status
    if security_evidence_report["status"] != "PASSED":
        combined_security_status = security_evidence_report["status"]
    if static_security_status in {"FAILED", "BLOCKED", "INCOMPLETE", "REVIEW_REQUIRED"}:
        combined_security_status = static_security_status


    warnings.extend(security_result.warnings)
    warnings.extend(dependency_result.warnings)
    warnings.extend(
        f"Static security finding {finding.rule_id} ({finding.severity}) "
        f"at {finding.path}:{finding.line}."
        for finding in security_result.findings
    )

    # Run target-language test suites only inside an explicitly configured,
    # already-available validation image. Never pull an image automatically.
    validation_image = os.environ.get("POLYMIGRATE_DOCKER_IMAGE_GO", "").strip() or None
    suite_result = validate_generated_project(
        result.output_root, target_language.id, validation_image
    )
    for gate_name in ("unit_tests", "integration_tests", "e2e_tests"):
        gates[gate_name] = suite_result.gates.get(gate_name, "NOT_RUN")
    if validation_image and suite_result.gates.get("target_build", "NOT_RUN") != "NOT_RUN":
        gates["target_build"] = suite_result.gates["target_build"]
    if validation_image:
        vet_execution = next(
            (item for item in suite_result.executions if item.command_id == "build-go-vet"),
            None,
        )
        if vet_execution is not None:
            gates["go_vet"] = vet_execution.status
    executions.extend(suite_result.to_dict()["executions"])
    warnings.extend(suite_result.warnings)

    if not args.behavior_spec:
        behavior = {
            "status": "NOT_RUN",
            "cases_checked": 0,
            "warnings": [
                "No behavior spec was supplied; behavior equivalence was not tested."
            ],
        }
        warnings.extend(behavior["warnings"])
    else:
        source_image = os.environ.get("POLYMIGRATE_DOCKER_IMAGE_PYTHON", "").strip() or None
        target_image = os.environ.get("POLYMIGRATE_DOCKER_IMAGE_GO", "").strip() or None
        comparison = compare_behavior(
            args.behavior_spec, args.source, result.output_root,
            source_image, target_image,
        )
        behavior = comparison.to_dict()
        gates["behavior_comparison"] = comparison.status
        warnings.extend(comparison.warnings)

    overall_status = _derive_final_status(
        gates,
        security_status=combined_security_status,
        dependency_status=dependency_result.status,
        required_gates={
            "target_build",
            "go_vet",
            "unit_tests",
            "integration_tests",
            "e2e_tests",
            "behavior_comparison",
        },
    )

    summary = {
        "status": overall_status,
        "strategy": "deterministic",
        "source_language": result.source_language,
        "target_language": result.target_language,
        "generated_files": list(result.generated_files),
        "source_inventory": {
            "inventory_mode": source_project.metadata.get("inventory_mode"),
            "parser_backends": source_project.metadata.get("parser_backends", []),
        },
        "dependency_inventory": [],
        "library_resolution": [],
        "warnings": warnings,
        "validation_image": validation_image,
        "repair": {
            "status": "NOT_RUN",
            "attempts": [],
            "warnings": ["AI repair is disabled for deterministic strategy."],
        },
        "static_security_scan": security_result.to_dict(),
        "external_security_evidence": security_evidence_report,
        "security_review_status": combined_security_status,
        "dependency_wiring_review": dependency_result.to_dict(),
        "behavior_comparison": behavior,
        "validation_gates": gates,
        "validation_results": {
            "gates": gates,
            "executions": executions,
            "warnings": warnings,
        },
        "note": (
            "Offline deterministic translation for a constrained Python-to-Go subset. "
            "No source code is sent to an AI provider. Unsupported syntax is rejected. "
            "Build/vet checks do not prove full behavior equivalence; unrun gates remain "
            "NOT_RUN. Static security scanning is heuristic, not a comprehensive audit. "
            "External security evidence must be supplied by trusted scanner execution; "
            "the aggregator does not verify scanner provenance."
        ),
    }
    (result.output_root / "migration-review.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 3 if overall_status == "BLOCKED" else 0


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
        if args.list_models:
            compatible = [provider for provider in configured if callable(getattr(provider, "list_models", None))]
            if not compatible:
                print("Model discovery could not run: no configured OpenAI-compatible providers are available.", file=sys.stderr)
                return 1
            failed = False
            for provider in compatible:
                try:
                    model_ids = provider.list_models()
                    print(f"Models ({provider.provider_id}):")
                    for model_id in model_ids:
                        print(f"- {model_id}")
                except Exception as exc:
                    failed = True
                    print(f"Model discovery: FAIL ({provider.provider_id}; {type(exc).__name__})", file=sys.stderr)
            return 1 if failed else 0
        if not args.check:
            return 0
        if not configured:
            print("Provider connectivity check could not run: no providers are configured.", file=sys.stderr)
            return 1
        failed = False
        for provider in configured:
            try:
                capabilities = provider.get_capabilities()
                response = provider.generate(ModelRequest(
                    task="provider_connectivity_check",
                    prompt='Return only this JSON object: {"status":"ok"}',
                    context={"purpose": "source-free connectivity check"},
                    require_structured_output=capabilities.structured_output,
                ))
                payload = response.structured_data
                if payload is None:
                    payload = json.loads(response.content)
                if not isinstance(payload, dict) or payload.get("status") != "ok":
                    raise ValueError("unexpected health-check response")
                print(f"  connectivity: PASS ({provider.provider_id})")
            except Exception as exc:
                failed = True
                # Do not print exception text: some third-party errors may contain request details.
                print(f"  connectivity: FAIL ({provider.provider_id}; {type(exc).__name__})")
        return 1 if failed else 0
    if args.command == "migrate":
        try:
            language_registry = LanguageRegistry()
            source_language = language_registry.get(args.source_language)
            target_language = language_registry.get(args.target_language)
            if args.strategy == "deterministic":
                return _run_deterministic_migration(args, source_language, target_language)
            if not args.allow_source_upload:
                raise PermissionError("Source upload is disabled; pass --allow-source-upload to enable external AI analysis")
            if not args.provider:
                raise ValueError("--provider is required when --strategy llm is selected")
            knowledge_db = os.environ.get("POLYMIGRATE_KNOWLEDGE_DB", "").strip()
            cache_drafts = os.environ.get("POLYMIGRATE_CACHE_DRAFTS", "").strip().lower() in {"1", "true", "yes"}
            if cache_drafts and not knowledge_db:
                raise ValueError("POLYMIGRATE_CACHE_DRAFTS requires POLYMIGRATE_KNOWLEDGE_DB")
            knowledge_store = MigrationKnowledgeStore(Path(knowledge_db).expanduser()) if knowledge_db else None
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
            selected_provider = providers.get(args.provider)
            # Enforce explicit model selection for providers that expose a model_id.
            # Lightweight/custom providers used by integrations may implement generate()
            # without a model_id attribute and should remain valid.
            selected_model = getattr(selected_provider, "model_id", None)
            if selected_model is not None and not str(selected_model).strip():
                raise ValueError(
                    f"Provider '{args.provider}' has no generation model configured; "
                    "run 'polymigrate providers --list-models', set the model ID, and retry"
                )
            source_adapter = InventorySourceAdapter(source_language.id, source_language.extensions)
            source_project = source_adapter.analyze(args.source)
            source_manifests, manifest_scan_warnings = scan_project_manifests(args.source)
            source_manifest_fingerprint = fingerprint_payload(source_manifests)
            context["source_manifests"] = source_manifests
            context["manifest_scan_warnings"] = manifest_scan_warnings
            context["reconstruct_manifests"] = bool(source_manifests)
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
                    manifest_context=source_manifests,
                )
                dependency_inventory = list(gap_plan.observed_dependencies)
                dependency_warnings.extend(gap_plan.warnings)
                resolution_workflow = LibraryResolutionWorkflow(providers)
                for gap in gap_plan.gaps:
                    problem_fingerprint = fingerprint_payload({
                        "kind": "library_resolution", "source_language": source_language.id,
                        "source_library": gap.source_library, "target_language": target_language.id,
                        "required_capabilities": list(gap.required_capabilities),
                        "source_manifest_fingerprint": source_manifest_fingerprint,
                    })
                    toolchain_fingerprint = fingerprint_payload({
                        "library_resolution_schema": 1, "target_language": target_language.id,
                    })
                    cached_summary = None
                    cached_record = None
                    if knowledge_store:
                        try:
                            verified_records = knowledge_store.find_reusable(
                                problem_fingerprint=problem_fingerprint, source_language=source_language.id,
                                target_language=target_language.id, toolchain_fingerprint=toolchain_fingerprint,
                                project_scope=project_scope or "",
                            )
                            for record in verified_records:
                                if record.solution.get("kind") == "library_resolution" and isinstance(record.solution.get("summary"), dict):
                                    cached_summary, cached_record = dict(record.solution["summary"]), record
                                    cached_summary["cache_status"] = "VERIFIED_REUSE"
                                    break
                            if cached_summary is None and cache_drafts and project_scope:
                                drafts = knowledge_store.find_cached_draft(
                                    problem_fingerprint=problem_fingerprint, source_language=source_language.id,
                                    target_language=target_language.id, toolchain_fingerprint=toolchain_fingerprint,
                                    project_scope=project_scope,
                                )
                                for record in drafts:
                                    solution = record.solution
                                    cached_at = solution.get("cached_at")
                                    summary_value = solution.get("summary")
                                    if (solution.get("kind") == "library_resolution" and isinstance(summary_value, dict)
                                            and isinstance(cached_at, (int, float)) and 0 <= time.time() - cached_at <= 7 * 86400):
                                        cached_summary, cached_record = dict(summary_value), record
                                        cached_summary["cache_status"] = "UNVERIFIED_SAME_PROJECT_CACHE"
                                        break
                        except Exception as cache_exc:
                            resolution_warnings.append(f"Library knowledge lookup failed ({type(cache_exc).__name__}); fresh research will be used.")
                    if cached_summary is not None and cached_record is not None:
                        cached_summary["source_library"] = gap.source_library
                        cached_summary["required_capabilities"] = list(gap.required_capabilities)
                        cached_summary["reason"] = gap.reason
                        cached_summary["evidence_files"] = list(gap.evidence_files)
                        cached_summary["knowledge_record_id"] = cached_record.record_id
                        cached_summary["problem_fingerprint"] = problem_fingerprint
                        cached_summary["toolchain_fingerprint"] = toolchain_fingerprint
                        if cached_summary.get("cache_status") != "VERIFIED_REUSE":
                            resolution_warnings.append(f"Reused an unverified library decision for {gap.source_library} from this project's cache; package metadata may be stale.")
                        library_resolutions.append(cached_summary)
                        continue
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
                        summary["problem_fingerprint"] = problem_fingerprint
                        summary["toolchain_fingerprint"] = toolchain_fingerprint
                        if knowledge_store and cache_drafts and project_scope:
                            # Drafts must be unique per project scope. Otherwise an unverified draft
                            # from another project can overwrite a verified/shareable record for the
                            # same library gap because problem_fingerprint is intentionally project-agnostic.
                            record_id = "library-" + problem_fingerprint[:16] + "-" + project_scope[:12]
                            summary["knowledge_record_id"] = record_id
                            summary["cache_status"] = "UNVERIFIED_CACHED"
                            try:
                                knowledge_store.save(KnowledgeRecord(
                                    record_id=record_id, problem_fingerprint=problem_fingerprint,
                                    source_language=source_language.id, target_language=target_language.id,
                                    toolchain_fingerprint=toolchain_fingerprint, project_scope=project_scope,
                                    solution={"kind": "library_resolution", "cached_at": time.time(), "summary": summary},
                                    validation_evidence=(), verified=False, shareable=False,
                                ))
                            except Exception as cache_exc:
                                resolution_warnings.append(f"Library decision cache write failed ({type(cache_exc).__name__}); migration will continue.")
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
            context["reconstruct_manifests"] = bool(source_manifests or library_resolutions)
            context["dependency_planning_warnings"] = dependency_warnings
            context["library_resolution_warnings"] = resolution_warnings

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
            static_security_result = review_generated_output(result.output_root)
            dependency_wiring_result = review_dependency_wiring(result.output_root, target_language.id)
            behavior_result = None
            if args.behavior_spec is not None:
                source_image_variable = f"POLYMIGRATE_DOCKER_IMAGE_{source_language.id.upper()}"
                source_image = os.environ.get(source_image_variable, "").strip() or None
                behavior_result = compare_behavior(
                    args.behavior_spec, args.source, result.output_root,
                    source_image, validation_image,
                )
                validation.gates["behavior_comparison"] = behavior_result.status
            gates = validation.gates
            if knowledge_store and library_resolutions:
                required_gates = MigrationKnowledgeStore.REQUIRED_VERIFICATION_GATES
                if all(gates.get(gate) == "PASSED" for gate in required_gates):
                    evidence = tuple({"gate": gate, "status": gates[gate], "source": "validation-suite"}
                                    for gate in sorted(required_gates))
                    for library_summary in library_resolutions:
                        record_id = library_summary.get("knowledge_record_id")
                        if not isinstance(record_id, str) or library_summary.get("cache_status") == "VERIFIED_REUSE":
                            continue
                        try:
                            knowledge_store.promote_verified(record_id, evidence, shareable=True)
                            library_summary["cache_status"] = "VERIFIED_SHARED"
                        except (ValueError, OSError, RuntimeError) as exc:
                            resolution_warnings.append(f"Library decision was not promoted to shared knowledge ({type(exc).__name__}).")
                elif any(isinstance(item.get("knowledge_record_id"), str) for item in library_resolutions):
                    resolution_warnings.append("Library decisions remain unverified and project-scoped because not all required validation gates passed.")
            all_warnings = list(result.warnings) + list(validation.warnings) + list(repair_result.warnings) + list(resolution_warnings)
            all_warnings.extend(static_security_result.warnings)
            all_warnings.extend(dependency_wiring_result.warnings)
            all_warnings.extend(
                f"Static security finding {finding.rule_id} ({finding.severity}) at {finding.path}:{finding.line}."
                for finding in static_security_result.findings
            )
            if behavior_result is not None:
                all_warnings.extend(behavior_result.warnings)
            overall_status = _derive_final_status(
                gates,
                security_status=static_security_result.status,
                dependency_status=dependency_wiring_result.status,
                required_gates={
                    "target_build",
                    "unit_tests",
                    "integration_tests",
                    "e2e_tests",
                    "behavior_comparison",
                },
            )
            summary = {
                "status": overall_status, "source_language": result.source_language,
                "target_language": result.target_language, "generated_files": list(result.generated_files),
                "source_inventory": {
                    "inventory_mode": source_project.metadata.get("inventory_mode"),
                    "parser_backends": source_project.metadata.get("parser_backends", []),
                },
                "dependency_inventory": dependency_inventory, "library_resolution": library_resolutions,
                "warnings": all_warnings, "validation_image": validation_image,
                "repair": repair_result.to_dict(),
                "static_security_scan": static_security_result.to_dict(),
                "dependency_wiring_review": dependency_wiring_result.to_dict(),
                "behavior_comparison": behavior_result.to_dict() if behavior_result is not None else {
                    "status": "NOT_RUN", "cases_checked": 0,
                    "warnings": ["No behavior spec was supplied; behavior equivalence was not tested."],
                },
                "validation_gates": gates, "validation_results": validation.to_dict(),
                "note": "Experimental per-file translation with optional constrained target-manifest reconstruction; dependencies are not installed automatically and full-project behavior is not guaranteed. Static security scanning is heuristic and does not replace comprehensive security review.",
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
