"""Command-line interface."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from polymigrate.ai.config import build_provider_registry
from polymigrate.models import MigrationRequest
from polymigrate.planner import PlanningError, create_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polymigrate", description="Plan cross-language project migrations safely.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="Analyze a source project and write a migration plan")
    plan.add_argument("--source", required=True, type=Path, help="Source project directory")
    plan.add_argument("--from", dest="source_language", required=True, help="Source language ID")
    plan.add_argument("--to", dest="target_language", required=True, help="Target language ID")
    plan.add_argument("--output", required=True, type=Path, help="Output directory outside the source tree")
    plan.add_argument("--json", dest="json_path", type=Path, help="Optional path for a copy of the plan JSON")
    subparsers.add_parser("providers", help="Show configured AI providers without making network requests")
    return parser


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
