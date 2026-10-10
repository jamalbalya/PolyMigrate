"""Skill metadata registry. Skill text is data and never grants permissions."""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWED_TOOLS = frozenset({
    "read_source", "inspect_graph", "search_documentation", "inspect_package_metadata",
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
        if not skill.id or skill.id.strip().lower() != skill.id:
            raise ValueError("Skill id must be non-empty lowercase canonical text")
        if not skill.version.strip() or not skill.description.strip():
            raise ValueError("Skill version and description are required")
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
        for metadata_path in sorted(root.glob("*/skill.json")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                instructions = (metadata_path.parent / "SKILL.md").read_text(encoding="utf-8")
                if not isinstance(metadata, dict):
                    raise ValueError("metadata root must be an object")
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
