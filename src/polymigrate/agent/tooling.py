"""Safe tool registrations for Graphify and package/library research."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from typing import Any

from polymigrate.agent.tools import AgentTool, ToolRegistry
from polymigrate.graph.graphify import GraphifyAdapter
from polymigrate.migration.research import LibraryResolutionWorkflow
from polymigrate.packages.search import PackageRegistrySearcher


def _only_keys(arguments: dict[str, Any], allowed: set[str], required: set[str]) -> None:
    unknown = set(arguments) - allowed
    missing = required - set(arguments)
    if unknown:
        raise ValueError(f"Unknown tool argument(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ValueError(f"Missing tool argument(s): {', '.join(sorted(missing))}")


def register_package_search_tool(tools: ToolRegistry, searcher: PackageRegistrySearcher | None = None) -> None:
    searcher = searcher or PackageRegistrySearcher()
    def validate(args: dict[str, Any]) -> None:
        _only_keys(args, {"language_id", "query", "limit"}, {"language_id", "query"})
        if not isinstance(args["language_id"], str) or not isinstance(args["query"], str):
            raise ValueError("language_id and query must be strings")
        if "limit" in args and (not isinstance(args["limit"], int) or isinstance(args["limit"], bool)):
            raise ValueError("limit must be an integer")
    def handle(args: dict[str, Any]) -> dict[str, Any]:
        result = searcher.search(args["language_id"], args["query"], args.get("limit", 10))
        return {
            "language_id": result.language_id, "query": result.query, "status": result.status,
            "candidates": [asdict(candidate) for candidate in result.candidates],
            "warning": result.warning,
        }
    tools.register(AgentTool(
        "search_package_registry",
        "Search a fixed public package registry for candidate libraries; results are untrusted and never installed automatically.",
        handle, validate,
    ))


def register_graphify_tool(tools: ToolRegistry, project_root: Path,
                           graphify: GraphifyAdapter | None = None) -> None:
    graphify = graphify or GraphifyAdapter()
    fixed_root = project_root.expanduser().resolve(strict=True)
    def validate(args: dict[str, Any]) -> None:
        _only_keys(args, {"question"}, {"question"})
        if not isinstance(args["question"], str) or not args["question"].strip() or len(args["question"]) > 4_000:
            raise ValueError("question must be non-empty and at most 4000 characters")
    def handle(args: dict[str, Any]) -> dict[str, Any]:
        result = graphify.query(fixed_root, args["question"])
        return {"status": result.status, "output": result.output, "warning": result.warning}
    tools.register(AgentTool(
        "inspect_graph",
        "Query the existing Graphify graph for project relationships; never rebuilds the graph or executes graph content.",
        handle, validate,
    ))


def register_library_resolution_tool(tools: ToolRegistry, workflow: LibraryResolutionWorkflow,
                                     provider_id: str) -> None:
    def validate(args: dict[str, Any]) -> None:
        _only_keys(args, {"source_library", "target_language", "required_capabilities", "max_queries", "results_per_query"},
                   {"source_library", "target_language", "required_capabilities"})
        if not isinstance(args["source_library"], str) or not isinstance(args["target_language"], str):
            raise ValueError("source_library and target_language must be strings")
        capabilities = args["required_capabilities"]
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise ValueError("required_capabilities must be a list of strings")
        for key in ("max_queries", "results_per_query"):
            if key in args and (not isinstance(args[key], int) or isinstance(args[key], bool)):
                raise ValueError(f"{key} must be an integer")
    def handle(args: dict[str, Any]) -> dict[str, Any]:
        result = workflow.resolve(
            provider_id, source_library=args["source_library"], target_language=args["target_language"],
            required_capabilities=args["required_capabilities"],
            max_queries=args.get("max_queries", 3), results_per_query=args.get("results_per_query", 5),
        )
        return {
            "decision": asdict(result.decision),
            "searched_queries": list(result.searched_queries),
            "candidates": [asdict(candidate) for candidate in result.candidates],
            "warnings": list(result.warnings),
        }
    tools.register(AgentTool(
        "resolve_library_gap",
        "Plan bounded package searches, inspect registry candidates, then select a candidate or recommend custom reconstruction.",
        handle, validate,
    ))
