"""Skill metadata registry. Skill text is data and never grants permissions."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWED_TOOLS = frozenset({
    "read_source", "inspect_graph", "search_documentation", "inspect_package_metadata", "search_package_registry", "resolve_library_gap",
    "write_workspace", "run_build", "run_tests", "compare_behavior", "emit_report",
})

@dataclass(frozen=True)
class Skill:
    id: str
    version: str
    description: str
    input_contract: tuple[str, ...]
    output_contract: tuple[str, ...]
    allowed_tools: tuple[str, ...] = ()
    instructions: str = ""

class SkillRegistry:
    def __init__(self, allowed_tools: frozenset[str] | set[str] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._allowed_tools = frozenset(allowed_tools if allowed_tools is not None else DEFAULT_ALLOWED_TOOLS)

    def register(self, skill: Skill) -> None:
        if not isinstance(skill.id, str) or not skill.id.strip() or skill.id.strip().lower() != skill.id:
            raise ValueError("Skill id must be non-empty lowercase canonical text")
        if not isinstance(skill.version, str) or not skill.version.strip() or not isinstance(skill.description, str) or not skill.description.strip():
            raise ValueError("Skill version and description are required")
        if not isinstance(skill.instructions, str):
            raise ValueError("Skill instructions must be text")
        if len(skill.id) > 100 or len(skill.version) > 50 or len(skill.description) > 500:
            raise ValueError("Skill metadata exceeds the configured size limits")
        if len(skill.instructions) > 20_000:
            raise ValueError("Skill instructions exceed the 20000-character limit")
        if len(skill.input_contract) > 20 or len(skill.output_contract) > 20 or len(skill.allowed_tools) > 20:
            raise ValueError("Skill contracts and tool lists must contain at most 20 entries")
        if any(not isinstance(item, str) or not item.strip() or len(item) > 200
               for item in (*skill.input_contract, *skill.output_contract, *skill.allowed_tools)):
            raise ValueError("Skill contracts and tool names must be bounded non-empty strings")
        if len(set(skill.allowed_tools)) != len(skill.allowed_tools):
            raise ValueError("Skill allowed_tools must not contain duplicates")
        forbidden = sorted(set(skill.allowed_tools) - self._allowed_tools)
        if forbidden:
            raise ValueError(f"Skill requests tools outside the platform allowlist: {', '.join(forbidden)}")
        if skill.id in self._skills:
            raise ValueError(f"Skill already registered: {skill.id}")
        self._skills[skill.id] = skill

    def load_directory(self, root: Path) -> tuple[Skill, ...]:
        if not root.is_dir():
            raise ValueError(f"Skill directory does not exist: {root}")
        loaded: list[Skill] = []
        root_resolved = root.resolve(strict=True)
        for metadata_path in sorted(root.glob("*/skill.json")):
            instructions_path = metadata_path.parent / "SKILL.md"
            try:
                if metadata_path.is_symlink() or metadata_path.parent.is_symlink() or instructions_path.is_symlink():
                    raise ValueError("skill package may not use symlinked files")
                if metadata_path.stat().st_size > 1_000_000 or instructions_path.stat().st_size > 20_000:
                    raise ValueError("skill package exceeds the configured file size limits")
                if root_resolved not in metadata_path.resolve(strict=True).parents or root_resolved not in instructions_path.resolve(strict=True).parents:
                    raise ValueError("skill package paths must remain within the skill directory")
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                instructions = instructions_path.read_text(encoding="utf-8")
                if not isinstance(metadata, dict):
                    raise ValueError("metadata root must be an object")
                for key in ("id", "version", "description"):
                    if not isinstance(metadata.get(key), str):
                        raise ValueError(f"{key} must be a string")
                for key in ("input_contract", "output_contract", "allowed_tools"):
                    value = metadata.get(key, [])
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        raise ValueError(f"{key} must be a list of strings")
                skill = Skill(
                    id=metadata["id"], version=metadata["version"], description=metadata["description"],
                    input_contract=tuple(metadata.get("input_contract", [])),
                    output_contract=tuple(metadata.get("output_contract", [])),
                    allowed_tools=tuple(metadata.get("allowed_tools", [])), instructions=instructions)
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValueError(f"Invalid skill package at {metadata_path.parent}: {type(exc).__name__}") from exc
            self.register(skill)
            loaded.append(skill)
        return tuple(loaded)

    def get(self, skill_id: str) -> Skill:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {skill_id}") from exc

    def all(self) -> tuple[Skill, ...]:
        return tuple(self._skills[key] for key in sorted(self._skills))
