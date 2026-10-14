"""Command-line interface."""
from __future__ import annotations
import argparse
from dataclasses import replace
import ast
import json
import os
import re
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
from polymigrate.migration.context import build_source_project_index
from polymigrate.migration.llm_target import LLMTargetAdapter
from polymigrate.migration.manifests import scan_project_manifests
from polymigrate.migration.pipeline import AdapterRegistry, MigrationEngine
from polymigrate.migration.python_go_target import PythonToGoTargetAdapter
from polymigrate.migration.python_javascript_target import PythonToJavaScriptTargetAdapter
from polymigrate.migration.javascript_python_target import JavaScriptToPythonTargetAdapter
from polymigrate.migration.javascript_go_target import JavaScriptToGoTargetAdapter
from polymigrate.migration.javascript_csharp_target import JavaScriptToCSharpTargetAdapter
from polymigrate.migration.javascript_typescript_target import JavaScriptToTypeScriptTargetAdapter
from polymigrate.migration.javascript_rust_target import JavaScriptToRustTargetAdapter
from polymigrate.migration.javascript_php_target import JavaScriptToPHPTargetAdapter
from polymigrate.migration.javascript_java_target import JavaScriptToJavaTargetAdapter
from polymigrate.migration.javascript_kotlin_target import JavaScriptToKotlinTargetAdapter
from polymigrate.migration.go_python_target import GoToPythonTargetAdapter
from polymigrate.migration.go_javascript_target import GoToJavaScriptTargetAdapter
from polymigrate.migration.go_typescript_target import GoToTypeScriptTargetAdapter
from polymigrate.migration.go_csharp_target import GoToCSharpTargetAdapter
from polymigrate.migration.go_php_target import GoToPHPTargetAdapter
from polymigrate.migration.go_rust_target import GoToRustTargetAdapter
from polymigrate.migration.typescript_python_target import TypeScriptToPythonTargetAdapter
from polymigrate.migration.typescript_javascript_target import TypeScriptToJavaScriptTargetAdapter
from polymigrate.migration.typescript_go_target import TypeScriptToGoTargetAdapter
from polymigrate.migration.typescript_rust_target import TypeScriptToRustTargetAdapter
from polymigrate.migration.typescript_csharp_target import TypeScriptToCSharpTargetAdapter
from polymigrate.migration.typescript_php_target import TypeScriptToPHPTargetAdapter
from polymigrate.migration.typescript_java_target import TypeScriptToJavaTargetAdapter
from polymigrate.migration.typescript_kotlin_target import TypeScriptToKotlinTargetAdapter
from polymigrate.migration.python_typescript_target import PythonToTypeScriptTargetAdapter
from polymigrate.migration.python_java_target import PythonToJavaTargetAdapter
from polymigrate.migration.python_kotlin_target import PythonToKotlinTargetAdapter
from polymigrate.migration.python_cpp_target import PythonToCppTargetAdapter
from polymigrate.migration.python_c_target import PythonToCTargetAdapter
from polymigrate.migration.python_csharp_target import PythonToCSharpTargetAdapter
from polymigrate.migration.python_php_target import PythonToPHPTargetAdapter
from polymigrate.migration.python_rust_target import PythonToRustTargetAdapter
from polymigrate.migration.python_ruby_target import PythonToRubyTargetAdapter
from polymigrate.migration.python_swift_target import PythonToSwiftTargetAdapter
from polymigrate.migration.research import LibraryResolutionWorkflow
from polymigrate.models import MigrationRequest
from polymigrate.planner import PlanningError, create_plan
from polymigrate.skills.registry import SkillRegistry
from polymigrate.validation.repair import AutonomousRepairLoop
from polymigrate.validation.suite import validate_generated_project
from polymigrate.validation.behavior import compare_behavior
from polymigrate.validation.dependency_wiring import java_candidate_jar_imports, review_dependency_wiring
from polymigrate.security.static_review import review_generated_output
from polymigrate.security.evidence_gate import evaluate_security_evidence
from polymigrate.security.scanner_runner import run_local_security_scanners


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
    migrate.add_argument("--security-evidence", type=Path, help="Optional JSON report containing required_scanners and evidence from external scanners; provenance is not verified")
    return parser



def _load_security_evidence(path: Path | None):
    """Load externally produced scanner evidence without trusting its provenance."""
    if path is None:
        return evaluate_security_evidence((), required_scanners=())
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("security evidence JSON must contain an object")
    required = payload.get("required_scanners")
    evidence = payload.get("evidence")
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise ValueError("security evidence required_scanners must be a list of scanner IDs")
    if not isinstance(evidence, list) or not all(isinstance(item, dict) for item in evidence):
        raise ValueError("security evidence evidence must be a list of scanner report objects")
    return evaluate_security_evidence(evidence, required_scanners=required)


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





def _candidate_test_imports(root: Path, target_language: str) -> set[str]:
    """Collect imports from bounded, conventionally named test files only."""
    test_dirs = {"test", "tests", "__tests__", "integration", "e2e", "spec"}
    ignored_dirs = {".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "target"}
    suffixes = {
        "python": {".py"},
        "go": {".go"},
        "javascript": {".js", ".jsx", ".mjs", ".cjs"},
        "typescript": {".ts", ".tsx"},
        "ruby": {".rb"},
        "rust": {".rs"},
        "java": {".java"},
    }.get(target_language, set())
    imports: set[str] = set()
    try:
        resolved = root.resolve(strict=True)
    except OSError:
        return imports
    if not resolved.is_dir() or root.is_symlink():
        return imports
    for current, directories, filenames in os.walk(resolved, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories
            if name not in ignored_dirs and not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink() or path.suffix.lower() not in suffixes:
                continue
            relative = path.relative_to(resolved)
            lower_name = filename.lower()
            in_test_dir = any(part.lower() in test_dirs for part in relative.parts[:-1])
            test_name = (
                lower_name.startswith("test_")
                or lower_name.endswith("_test.py")
                or lower_name.endswith("_test.go")
                or lower_name.endswith("_test.rb")
                or lower_name.endswith("_test.rs")
                or lower_name.endswith("_test.java")
                or ".test." in lower_name
                or ".spec." in lower_name
            )
            if not in_test_dir and not test_name:
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            if target_language == "python":
                try:
                    tree = ast.parse(source)
                except (SyntaxError, RecursionError):
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(alias.name.split(".", 1)[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module.split(".", 1)[0])
            elif target_language in {"javascript", "typescript"}:
                for item in re.findall(
                    r"""(?m)(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*)['"]([^'"]+)['"]""",
                    source,
                ):
                    if item.startswith((".", "/", "node:")):
                        continue
                    parts = item.split("/")
                    imports.add("/".join(parts[:2]) if item.startswith("@") and len(parts) > 1 else parts[0])
            elif target_language == "go":
                source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
                for item in re.findall(
                    r'''(?m)^\s*import\s+(?:[A-Za-z_][A-Za-z0-9_]*\s+)?["']([^"']+)["']''',
                    source,
                ):
                    imports.add(item)
                for block in re.findall(r"(?s)\bimport\s*\((.*?)\)", source):
                    imports.update(re.findall(r'''["']([^"']+)["']''', block))
            elif target_language == "ruby":
                imports.update(re.findall(r"""(?m)^\s*require(?:_relative)?\s*\(?\s*['"]([^'"]+)['"]""", source))
            elif target_language == "rust":
                clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
                found = set(re.findall(
                    r"(?m)^\s*(?:pub\s+)?use\s+([A-Za-z_][A-Za-z0-9_]*)(?:::|(?:\s+as\s+[A-Za-z_][A-Za-z0-9_]*)?\s*;)",
                    clean,
                ))
                found.update(re.findall(
                    r"(?m)^\s*extern\s+crate\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", clean
                ))
                imports.update(item for item in found if item not in {"std", "core", "alloc", "crate", "self", "super"})
            elif target_language == "java":
                clean = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
                clean = re.sub(r"(?m)^\s*//.*$", "", clean)
                imports.update(re.findall(
                    r"(?m)^\s*import\s+(?:static\s+)?([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\s*;",
                    clean,
                ))
    return imports


def _candidate_dependency_integration_status(
    library_resolutions: list[dict[str, object]],
    dependency_review,
    gates: dict[str, str],
    target_language: str,
    project_root: Path | None = None,
    dependency_warnings: list[str] | tuple[str, ...] = (),
) -> tuple[str, list[str]]:
    """Require complete dependency evidence and resolved library gaps before a pass."""
    if dependency_warnings:
        return "NOT_RUN", [
            "Dependency-gap planning emitted warnings; the dependency inventory may be incomplete, so integration cannot be proven."
        ]
    unresolved = [item for item in library_resolutions if item.get("decision_type") != "candidate"]
    if unresolved:
        return "UNVERIFIED", [
            "One or more library gaps remain unresolved or require a custom/architectural implementation; dependency integration cannot be marked PASSED."
        ]
    candidates = list(library_resolutions)
    if not candidates:
        return "PASSED", [
            "No candidate library dependencies or unresolved library gaps were reported; candidate-specific dependency integration proof is not applicable."
        ]
    java_mapping_only_unverified = (
        target_language == "java"
        and dependency_review.status == "UNVERIFIED"
        and any("Java import-to-Maven/Gradle coordinate mapping is ambiguous" in item
                for item in dependency_review.warnings)
        and all(
            "Java import-to-Maven/Gradle coordinate mapping is ambiguous" in item
            or "Static import/manifest consistency" in item
            for item in dependency_review.warnings
        )
    )
    if dependency_review.status != "PASSED" and not java_mapping_only_unverified:
        return "NOT_RUN", ["Candidate dependency integration proof requires a PASSED dependency wiring review or resolvable Java JAR evidence."]
    if target_language not in {"go", "python", "javascript", "typescript", "ruby", "rust", "java"}:
        return "NOT_RUN", [f"Candidate dependency resolution/build proof is not implemented for target language {target_language}; this gate remains unverified."]
    for gate in ("target_build", "integration_tests", "behavior_comparison"):
        if gates.get(gate) != "PASSED":
            return "NOT_RUN", [f"Candidate dependency integration proof requires {gate}=PASSED."]
    declared = dependency_review.declared_dependencies
    observed_imports = dependency_review.observed_imports
    candidate_test_imports = _candidate_test_imports(project_root, target_language) if project_root is not None else set()

    def normalize(value: str) -> str:
        if target_language == "python":
            return re.sub(r"[-_.]+", "-", value).casefold()
        if target_language == "ruby":
            return re.sub(r"[^a-z0-9]", "", value.casefold())
        if target_language == "rust":
            return value.replace("-", "_").casefold()
        if target_language == "java":
            return value.rsplit(":", 1)[-1].casefold()
        if target_language in {"go", "javascript", "typescript"}:
            return value
        return value.casefold()

    for candidate in candidates:
        package = candidate.get("selected_package")
        if not isinstance(package, dict):
            return "NOT_RUN", ["Candidate has no resolved package identity; dependency integration cannot be proven."]
        package_name = package.get("name")
        registry = package.get("registry")
        if not isinstance(package_name, str) or not package_name.strip() or registry == "github-repositories":
            return "NOT_RUN", ["A repository reference without a package identity is not dependency integration proof."]
        if not any(normalize(item) == normalize(package_name) for item in declared):
            return "NOT_RUN", [f"Candidate package '{package_name}' is not proven present in target dependency declarations."]
        java_coordinate = None
        if target_language == "java":
            coordinates = [
                item for item in declared
                if ":" in item and normalize(item) == normalize(package_name)
            ]
            if len(coordinates) != 1:
                return "NOT_RUN", [f"Java candidate '{package_name}' does not map to exactly one declared Maven coordinate."]
            java_coordinate = coordinates[0]
            if project_root is None:
                return "NOT_RUN", ["Candidate-specific integration evidence requires the generated project root."]
            import_match = bool(java_candidate_jar_imports(project_root, java_coordinate, observed_imports))
        elif target_language == "python":
            import_match = any(normalize(item) == normalize(package_name) for item in observed_imports)
        elif target_language in {"javascript", "typescript"}:
            import_match = any(
                normalize(item) == normalize(package_name)
                or item.startswith(package_name + "/")
                for item in observed_imports
            )
        elif target_language == "ruby":
            import_match = any(normalize(item.split("/", 1)[0]) == normalize(package_name) for item in observed_imports)
        elif target_language == "rust":
            import_match = any(normalize(item.split("::", 1)[0]) == normalize(package_name) for item in observed_imports)
        elif target_language == "java":
            pass  # Exact class presence in the declared local JAR was checked above.
        else:
            import_match = any(
                normalize(item) == normalize(package_name)
                or item.startswith(package_name + ".")
                or item.startswith(package_name + "/")
                for item in observed_imports
            )
        if not import_match:
            if target_language == "java":
                return "NOT_RUN", [
                    f"Java candidate '{package_name}' has no exact imported-and-used class evidence in its declared project-local system-scope JAR."
                ]
            return "NOT_RUN", [f"Candidate package '{package_name}' is not observed in target source imports."]
        if project_root is None:
            return "NOT_RUN", ["Candidate-specific integration evidence requires the generated project root."]
        if target_language == "python":
            test_match = any(normalize(item) == normalize(package_name) for item in candidate_test_imports)
        elif target_language in {"javascript", "typescript"}:
            test_match = any(
                normalize(item) == normalize(package_name) or item.startswith(package_name + "/")
                for item in candidate_test_imports
            )
        elif target_language == "ruby":
            test_match = any(normalize(item.split("/", 1)[0]) == normalize(package_name) for item in candidate_test_imports)
        elif target_language == "rust":
            test_match = any(normalize(item.split("::", 1)[0]) == normalize(package_name) for item in candidate_test_imports)
        elif target_language == "java":
            test_match = bool(java_candidate_jar_imports(project_root, java_coordinate or "", candidate_test_imports, test_sources=True))
        else:
            test_match = any(
                normalize(item) == normalize(package_name) or item.startswith(package_name + "/")
                for item in candidate_test_imports
            )
        if not test_match:
            return "NOT_RUN", [f"No recognized integration/test file imports candidate package '{package_name}'; generic test success is insufficient."]
    if target_language == "java":
        return "PASSED", [
            "Java candidate class provenance was verified from the declared project-local JAR, production/test imports, and passing target build/integration/behavior gates."
        ]
    return "PASSED", ["Each candidate package is declared, imported by production code and a recognized test file, and the required target build/integration/behavior gates passed."]


def _promote_java_dependency_review_with_candidate_evidence(
    review, target_language: str, candidate_status: str, candidate_warnings: list[str]
):
    """Resolve Java's static coordinate ambiguity only when local-JAR evidence passed."""
    if (
        target_language != "java"
        or candidate_status != "PASSED"
        or review.status != "UNVERIFIED"
        or not any("Java candidate class provenance was verified from the declared project-local JAR" in item
                   for item in candidate_warnings)
        or not any("Java import-to-Maven/Gradle coordinate mapping is ambiguous" in item
                   for item in review.warnings)
    ):
        return review
    retained = tuple(
        item for item in review.warnings
        if "Java import-to-Maven/Gradle coordinate mapping is ambiguous" not in item
    )
    return replace(
        review,
        status="PASSED",
        warnings=retained + (
            "Java package-to-coordinate ambiguity was resolved by exact class entries in the declared local JAR and passing target build/integration/behavior evidence.",
        ),
    )


def _security_review_gate_status(scanner_result, static_review=None, dependency_review=None) -> str:
    """Require clean static review, trusted SAST/secret/SCA scans, and dependency consistency."""
    if scanner_result is None or static_review is None or dependency_review is None:
        return "INCOMPLETE"
    statuses = (scanner_result.status, static_review.status, dependency_review.status)
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAILED" in statuses:
        return "FAILED"
    if "REVIEW_REQUIRED" in statuses:
        return "REVIEW_REQUIRED"
    if (
        statuses != ("PASSED", "PASSED", "PASSED")
        or not getattr(scanner_result, "scanner_execution_recorded", False)
        or not getattr(scanner_result, "scanner_provenance_verified", False)
    ):
        return "INCOMPLETE"
    return "PASSED"


def _derive_final_status(
    gates: dict[str, str],
    *,
    security_status: str,
    dependency_status: str,
    required_gates: set[str],
) -> str:
    """Derive the public final status from validation evidence."""
    failed = {"FAILED", "BLOCKED", "TIMEOUT", "INCOMPLETE", "REVIEW_REQUIRED"}

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
    """Run an offline deterministic Python-to-target subset and local checks."""
    pair = (source_language.id, target_language.id)
    if pair not in {("typescript", "python"), ("go", "python"), ("go", "javascript"), ("go", "typescript"), ("go", "csharp"), ("go", "php"), ("go", "rust"), ("javascript", "python"), ("javascript", "go"), ("javascript", "csharp"), ("javascript", "typescript"), ("javascript", "rust"), ("javascript", "php"), ("javascript", "java"), ("javascript", "kotlin"), ("typescript", "javascript"), ("typescript", "go"), ("typescript", "rust"), ("typescript", "csharp"), ("typescript", "php"), ("typescript", "java"), ("typescript", "kotlin"), ("python", "go"), ("python", "javascript"), ("python", "typescript"), ("python", "kotlin"), ("python", "rust"), ("python", "java"), ("python", "php"), ("python", "ruby"), ("python", "cpp"), ("python", "csharp"), ("python", "c"), ("python", "swift")}:
        raise ValueError(
            "The deterministic strategy currently supports --from python --to go, javascript, typescript, kotlin, rust, java, php, ruby, cpp, csharp, c, or swift, "
            "--from javascript --to python, go, csharp, typescript, rust, php, java, or kotlin; --from go --to python, javascript, typescript, csharp, php, or rust; and --from typescript --to python, javascript, go, rust, csharp, php, java, or kotlin"
        )

    context = {}
    if args.context_json:
        context = json.loads(args.context_json.read_text(encoding="utf-8"))
        if not isinstance(context, dict):
            raise ValueError("context JSON must contain an object")

    source_extensions = (
        (".js", ".mjs", ".cjs")
        if pair in {("javascript", "python"), ("javascript", "go"), ("javascript", "csharp"), ("javascript", "typescript"), ("javascript", "rust"), ("javascript", "php"), ("javascript", "java"), ("javascript", "kotlin")}
        else (".ts",)
        if pair in {("typescript", "python"), ("typescript", "javascript"), ("typescript", "go"), ("typescript", "rust"), ("typescript", "csharp"), ("typescript", "php"), ("typescript", "java"), ("typescript", "kotlin")}
        else source_language.extensions
    )
    source_adapter = InventorySourceAdapter(
        source_language.id, source_extensions
    )
    source_project = source_adapter.analyze(args.source)

    adapters = AdapterRegistry()
    adapters.register_source(source_adapter)
    if pair == ("javascript", "python"):
        adapters.register_target(JavaScriptToPythonTargetAdapter())
    elif pair == ("javascript", "go"):
        adapters.register_target(JavaScriptToGoTargetAdapter())
    elif pair == ("javascript", "csharp"):
        adapters.register_target(JavaScriptToCSharpTargetAdapter())
    elif pair == ("javascript", "typescript"):
        adapters.register_target(JavaScriptToTypeScriptTargetAdapter())
    elif pair == ("javascript", "rust"):
        adapters.register_target(JavaScriptToRustTargetAdapter())
    elif pair == ("javascript", "php"):
        adapters.register_target(JavaScriptToPHPTargetAdapter())
    elif pair == ("javascript", "java"):
        adapters.register_target(JavaScriptToJavaTargetAdapter())
    elif pair == ("javascript", "kotlin"):
        adapters.register_target(JavaScriptToKotlinTargetAdapter())
    elif pair == ("go", "python"):
        adapters.register_target(GoToPythonTargetAdapter())
    elif pair == ("go", "javascript"):
        adapters.register_target(GoToJavaScriptTargetAdapter())
    elif pair == ("go", "typescript"):
        adapters.register_target(GoToTypeScriptTargetAdapter())
    elif pair == ("go", "csharp"):
        adapters.register_target(GoToCSharpTargetAdapter())
    elif pair == ("go", "php"):
        adapters.register_target(GoToPHPTargetAdapter())
    elif pair == ("go", "rust"):
        adapters.register_target(GoToRustTargetAdapter())
    elif pair == ("typescript", "javascript"):
        adapters.register_target(TypeScriptToJavaScriptTargetAdapter())
    elif pair == ("typescript", "python"):
        adapters.register_target(TypeScriptToPythonTargetAdapter())
    elif pair == ("typescript", "go"):
        adapters.register_target(TypeScriptToGoTargetAdapter())
    elif pair == ("typescript", "rust"):
        adapters.register_target(TypeScriptToRustTargetAdapter())
    elif pair == ("typescript", "csharp"):
        adapters.register_target(TypeScriptToCSharpTargetAdapter())
    elif pair == ("typescript", "php"):
        adapters.register_target(TypeScriptToPHPTargetAdapter())
    elif pair == ("typescript", "java"):
        adapters.register_target(TypeScriptToJavaTargetAdapter())
    elif pair == ("typescript", "kotlin"):
        adapters.register_target(TypeScriptToKotlinTargetAdapter())
    elif target_language.id == "go":
        adapters.register_target(PythonToGoTargetAdapter())
    elif target_language.id == "javascript":
        adapters.register_target(PythonToJavaScriptTargetAdapter())
    elif target_language.id == "typescript":
        adapters.register_target(PythonToTypeScriptTargetAdapter())
    elif target_language.id == "kotlin":
        adapters.register_target(PythonToKotlinTargetAdapter())
    elif target_language.id == "rust":
        adapters.register_target(PythonToRustTargetAdapter())
    elif target_language.id == "php":
        adapters.register_target(PythonToPHPTargetAdapter())
    elif target_language.id == "ruby":
        adapters.register_target(PythonToRubyTargetAdapter())
    elif target_language.id == "cpp":
        adapters.register_target(PythonToCppTargetAdapter())
    elif target_language.id == "c":
        adapters.register_target(PythonToCTargetAdapter())
    elif target_language.id == "csharp":
        adapters.register_target(PythonToCSharpTargetAdapter())
    elif target_language.id == "swift":
        adapters.register_target(PythonToSwiftTargetAdapter())
    else:
        adapters.register_target(PythonToJavaTargetAdapter())
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
        "dependency_integration": "PASSED",
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

    main_source = result.output_root / ("main.py" if target_language.id == "python" else "main.go" if target_language.id == "go" else "src/main.rs" if target_language.id == "rust" else "main.js" if target_language.id == "javascript" else "main.ts" if target_language.id == "typescript" else "Main.kt" if target_language.id == "kotlin" else "Main.java" if target_language.id == "java" else "main.php" if target_language.id == "php" else "main.rb" if target_language.id == "ruby" else "Program.cs" if target_language.id == "csharp" else "main.c" if target_language.id == "c" else "main.swift" if target_language.id == "swift" else "main.cpp")
    if target_language.id == "python":
        python = shutil.which("python3") or shutil.which("python")
        python_files = sorted(result.output_root.rglob("*.py"))
        if not python or not python_files:
            gates["target_build"] = "BLOCKED"
            warnings.append("Python validation is blocked because Python and at least one generated .py file are required.")
        else:
            syntax_statuses = [
                run_check(f"target_build_python_{index}", [python, "-m", "py_compile", str(path)])
                for index, path in enumerate(python_files)
            ]
            gates["target_build"] = "PASSED" if all(status == "PASSED" for status in syntax_statuses) else next(
                status for status in syntax_statuses if status != "PASSED"
            )
            if gates["target_build"] == "PASSED" and main_source.is_file():
                runtime_status = run_check("target_runtime_smoke_python", [python, str(main_source)])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "go":
        go = shutil.which("go")
        gofmt = shutil.which("gofmt")
        if not go or not gofmt:
            gates["target_build"] = "BLOCKED"
            warnings.append("Go validation is blocked because both go and gofmt must be available.")
        else:
            format_status = run_check("gofmt", [gofmt, "-w", str(main_source)])
            if format_status == "PASSED":
                with tempfile.TemporaryDirectory(prefix="polymigrate-go-build-") as build_dir:
                    binary_path = str(Path(build_dir) / "program")
                    build_status = run_check("target_build", [go, "build", "-o", binary_path, "main.go"])
                    gates["target_build"] = build_status
                    if build_status == "PASSED":
                        gates["go_vet"] = run_check("go_vet", [go, "vet", "main.go"])
                    else:
                        warnings.append("go vet was not run because the Go build did not pass.")
            else:
                gates["target_build"] = format_status
                warnings.append("Go formatting failed; build and vet were not run.")
    elif target_language.id == "javascript":
        node = shutil.which("node")
        if not node:
            gates["target_build"] = "BLOCKED"
            warnings.append("JavaScript validation is blocked because node is not available.")
        else:
            gates["target_build"] = run_check("target_build", [node, "--check", str(main_source)])
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "typescript":
        tsc = shutil.which("tsc")
        node = shutil.which("node")
        if not tsc or not node:
            gates["target_build"] = "BLOCKED"
            warnings.append("TypeScript validation is blocked because both tsc and node must be available.")
        else:
            with tempfile.TemporaryDirectory(prefix="polymigrate-typescript-build-") as build_dir:
                build_status = run_check(
                    "target_build_typescript",
                    [tsc, "--strict", "--target", "ES2020", "--module", "commonjs",
                     "--outDir", build_dir, str(main_source)],
                )
                gates["target_build"] = build_status
                if build_status == "PASSED":
                    compiled_js = Path(build_dir) / main_source.with_suffix(".js").name
                    runtime_status = run_check("target_runtime_smoke_typescript", [node, str(compiled_js)])
                    if runtime_status != "PASSED":
                        gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "kotlin":
        kotlinc = shutil.which("kotlinc")
        java = shutil.which("java")
        if not kotlinc or not java or not main_source.is_file():
            gates["target_build"] = "BLOCKED"
            warnings.append("Kotlin validation is blocked because kotlinc, java, and Main.kt must be available.")
        else:
            with tempfile.TemporaryDirectory(prefix="polymigrate-kotlin-build-") as build_dir:
                jar_path = Path(build_dir) / "polymigrate.jar"
                compile_status = run_check(
                    "target_build_kotlin",
                    [kotlinc, str(main_source), "-include-runtime", "-d", str(jar_path)],
                )
                gates["target_build"] = compile_status
                if compile_status == "PASSED":
                    runtime_status = run_check("target_runtime_smoke_kotlin", [java, "-jar", str(jar_path)])
                    if runtime_status != "PASSED":
                        gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "java":
        javac = shutil.which("javac")
        java = shutil.which("java")
        if not javac or not java:
            gates["target_build"] = "BLOCKED"
            warnings.append("Java validation is blocked because both javac and java must be available.")
        else:
            compile_status = run_check("target_build", [javac, str(main_source)])
            gates["target_build"] = compile_status
            if compile_status == "PASSED":
                runtime_status = run_check("target_runtime_smoke", [java, "-cp", ".", "Main"])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "php":
        php = shutil.which("php")
        php_files = sorted(result.output_root.rglob("*.php"))
        if not php or not php_files:
            gates["target_build"] = "BLOCKED"
            warnings.append("PHP validation is blocked because php must be available and at least one generated PHP file must exist.")
        else:
            syntax_statuses = [
                run_check(f"target_build_php_{index}", [php, "-l", str(path)])
                for index, path in enumerate(php_files)
            ]
            gates["target_build"] = "PASSED" if all(status == "PASSED" for status in syntax_statuses) else next(
                status for status in syntax_statuses if status != "PASSED"
            )
            main_php = result.output_root / "main.php"
            if gates["target_build"] == "PASSED" and main_php.is_file():
                runtime_status = run_check("target_runtime_smoke", [php, str(main_php)])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "ruby":
        ruby = shutil.which("ruby")
        ruby_files = sorted(result.output_root.rglob("*.rb"))
        if not ruby or not ruby_files:
            gates["target_build"] = "BLOCKED"
            warnings.append("Ruby validation is blocked because ruby must be available and at least one generated Ruby file must exist.")
        else:
            syntax_statuses = [
                run_check(f"target_build_ruby_{index}", [ruby, "-c", str(path)])
                for index, path in enumerate(ruby_files)
            ]
            gates["target_build"] = "PASSED" if all(status == "PASSED" for status in syntax_statuses) else next(
                status for status in syntax_statuses if status != "PASSED"
            )
            main_ruby = result.output_root / "main.rb"
            if gates["target_build"] == "PASSED" and main_ruby.is_file():
                runtime_status = run_check("target_runtime_smoke", [ruby, str(main_ruby)])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "c":
        compiler = shutil.which("gcc")
        c_files = sorted(result.output_root.rglob("*.c"))
        executable = result.output_root / "polymigrate-runner"
        if not compiler or len(c_files) != 1:
            gates["target_build"] = "BLOCKED"
            warnings.append("C validation is blocked because gcc must be available and exactly one generated .c file must exist.")
        else:
            compile_status = run_check(
                "target_build_c",
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(c_files[0]), "-o", str(executable)],
            )
            gates["target_build"] = compile_status
            if compile_status == "PASSED":
                runtime_status = run_check("target_runtime_smoke", [str(executable)])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "swift":
        compiler = shutil.which("swiftc")
        swift_files = sorted(result.output_root.rglob("*.swift"))
        executable = result.output_root / "polymigrate-runner"
        if not compiler or len(swift_files) != 1:
            gates["target_build"] = "BLOCKED"
            warnings.append("Swift validation is blocked because swiftc must be available and exactly one generated .swift file must exist.")
        else:
            compile_status = run_check(
                "target_build_swift",
                [compiler, "-warnings-as-errors", str(swift_files[0]), "-o", str(executable)],
            )
            gates["target_build"] = compile_status
            if compile_status == "PASSED":
                runtime_status = run_check("target_runtime_smoke", [str(executable)])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "cpp":
        compiler = shutil.which("g++")
        cpp_files = sorted(result.output_root.rglob("*.cpp"))
        executable = result.output_root / "polymigrate-runner"
        if not compiler or len(cpp_files) != 1:
            gates["target_build"] = "BLOCKED"
            warnings.append("C++ validation is blocked because g++ must be available and exactly one generated .cpp file must exist.")
        else:
            compile_status = run_check(
                "target_build_cpp",
                [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(cpp_files[0]), "-o", str(executable)],
            )
            gates["target_build"] = compile_status
            if compile_status == "PASSED":
                runtime_status = run_check("target_runtime_smoke", [str(executable)])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    elif target_language.id == "csharp":
        dotnet = shutil.which("dotnet")
        project_file = result.output_root / "PolyMigrate.csproj"
        if not dotnet or not project_file.is_file():
            gates["target_build"] = "BLOCKED"
            warnings.append("C# validation is blocked because dotnet and the generated PolyMigrate.csproj must be available.")
        else:
            build_status = run_check(
                "target_build_csharp",
                [dotnet, "build", str(project_file), "--configuration", "Release", "--nologo", "--verbosity", "quiet"],
            )
            gates["target_build"] = build_status
            if build_status == "PASSED":
                assembly = result.output_root / "bin" / "Release" / "net8.0" / "PolyMigrate.dll"
                runtime_status = run_check("target_runtime_smoke", [dotnet, str(assembly)])
                if runtime_status != "PASSED":
                    gates["target_build"] = runtime_status
        gates["go_vet"] = "NOT_APPLICABLE"
    else:
        cargo = shutil.which("cargo")
        if not cargo:
            gates["target_build"] = "BLOCKED"
            warnings.append("Rust validation is blocked because cargo is not available.")
        else:
            gates["target_build"] = run_check("target_build", [cargo, "check", "--offline"])
        gates["go_vet"] = "NOT_APPLICABLE"

    security_result = review_generated_output(result.output_root)
    trusted_security_result = run_local_security_scanners(result.output_root, target_language.id)
    security_evidence_result = _load_security_evidence(args.security_evidence)
    dependency_result = review_dependency_wiring(result.output_root, target_language.id)
    gates["dependency_wiring"] = dependency_result.status
    gates["dependency_integration"] = "PASSED"
    gates["security_review"] = _security_review_gate_status(trusted_security_result, security_result, dependency_result)
    warnings.append("No candidate library dependencies were selected; candidate-specific dependency integration proof is not applicable.")

    warnings.extend(security_result.warnings)
    warnings.extend(dependency_result.warnings)
    warnings.extend(
        f"Static security finding {finding.rule_id} ({finding.severity}) "
        f"at {finding.path}:{finding.line}."
        for finding in security_result.findings
    )

    # Run target-language test suites only inside an explicitly configured,
    # already-available validation image. Never pull an image automatically.
    target_image_variable = f"POLYMIGRATE_DOCKER_IMAGE_{target_language.id.upper()}"
    validation_image = os.environ.get(target_image_variable, "").strip() or None
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
        source_image_variable = f"POLYMIGRATE_DOCKER_IMAGE_{source_language.id.upper()}"
        source_image = os.environ.get(source_image_variable, "").strip() or None
        target_image = os.environ.get(target_image_variable, "").strip() or None
        comparison = compare_behavior(
            args.behavior_spec, args.source, result.output_root,
            source_image, target_image,
        )
        behavior = comparison.to_dict()
        gates["behavior_comparison"] = comparison.status
        warnings.extend(comparison.warnings)

    overall_status = _derive_final_status(
        gates,
        security_status=security_result.status,
        dependency_status=dependency_result.status,
        required_gates=(
            {
                "target_build", "go_vet", "unit_tests", "integration_tests",
                "e2e_tests", "behavior_comparison", "dependency_integration", "security_review",
            }
            if target_language.id == "go" else
            {
                "target_build", "unit_tests", "integration_tests", "e2e_tests",
                "behavior_comparison", "dependency_integration", "security_review",
            }
        ),
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
        "external_security_evidence": security_evidence_result.to_dict(),
        "local_security_scan": trusted_security_result.to_dict(),
        "dependency_wiring_review": dependency_result.to_dict(),
        "behavior_comparison": behavior,
        "validation_gates": gates,
        "validation_results": {
            "gates": gates,
            "executions": executions,
            "warnings": warnings,
        },
        "note": (
            "Offline deterministic translation for constrained language-pair subsets. "
            "No source code is sent to an AI provider. Unsupported syntax is rejected. "
            "Build/vet checks do not prove full behavior equivalence; unrun gates remain "
            "NOT_RUN. Static security scanning is heuristic, not a comprehensive audit."
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
            context["source_project_index"] = build_source_project_index(source_project)
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
            trusted_security_result = run_local_security_scanners(result.output_root, target_language.id)
            security_evidence_result = _load_security_evidence(args.security_evidence)
            dependency_wiring_result = review_dependency_wiring(result.output_root, target_language.id)
            validation.gates["dependency_wiring"] = dependency_wiring_result.status
            validation.gates["security_review"] = _security_review_gate_status(trusted_security_result, static_security_result, dependency_wiring_result)
            behavior_result = None
            if args.behavior_spec is not None:
                source_image_variable = f"POLYMIGRATE_DOCKER_IMAGE_{source_language.id.upper()}"
                source_image = os.environ.get(source_image_variable, "").strip() or None
                behavior_result = compare_behavior(
                    args.behavior_spec, args.source, result.output_root,
                    source_image, validation_image,
                )
                validation.gates["behavior_comparison"] = behavior_result.status
            dependency_integration_status, dependency_integration_warnings = _candidate_dependency_integration_status(
                library_resolutions, dependency_wiring_result, validation.gates, target_language.id,
                result.output_root, dependency_warnings=dependency_warnings,
            )
            dependency_wiring_result = _promote_java_dependency_review_with_candidate_evidence(
                dependency_wiring_result, target_language.id,
                dependency_integration_status, dependency_integration_warnings,
            )
            validation.gates["dependency_wiring"] = dependency_wiring_result.status
            validation.gates["dependency_integration"] = dependency_integration_status
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
                            if library_summary.get("decision_type") == "candidate":
                                library_summary["implementation_status"] = "VERIFIED_INTEGRATION"
                        except (ValueError, OSError, RuntimeError) as exc:
                            resolution_warnings.append(f"Library decision was not promoted to shared knowledge ({type(exc).__name__}).")
                elif any(isinstance(item.get("knowledge_record_id"), str) for item in library_resolutions):
                    resolution_warnings.append("Library decisions remain unverified and project-scoped because not all required validation gates passed.")
            all_warnings = list(result.warnings) + list(validation.warnings) + list(repair_result.warnings) + list(resolution_warnings)
            all_warnings.extend(static_security_result.warnings)
            all_warnings.extend(dependency_wiring_result.warnings)
            all_warnings.extend(dependency_integration_warnings)
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
                    "dependency_integration",
                    "security_review",
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
                "external_security_evidence": security_evidence_result.to_dict(),
                "trusted_security_scan": trusted_security_result.to_dict(),
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
