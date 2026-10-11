"""Explicitly registered tools; model output can never name arbitrary Python callables."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

ToolHandler = Callable[[dict[str, Any]], Any]
ArgumentValidator = Callable[[dict[str, Any]], None]
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    handler: ToolHandler
    validate_arguments: ArgumentValidator | None = None


class ToolRegistry:
    def __init__(self, max_output_bytes: int = 64_000) -> None:
        if max_output_bytes < 1:
            raise ValueError("max_output_bytes must be positive")
        self._tools: dict[str, AgentTool] = {}
        self._max_output_bytes = max_output_bytes

    def register(self, tool: AgentTool) -> None:
        if not _TOOL_NAME.fullmatch(tool.name):
            raise ValueError("Tool names must be lowercase snake_case and 2-64 characters")
        if not tool.description.strip():
            raise ValueError("Tool description is required")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        tool = self._tools.get(name)
        if tool is None:
            raise PermissionError(f"Tool is not allowlisted: {name}")
        if tool.validate_arguments:
            tool.validate_arguments(arguments)
        result = tool.handler(arguments)
        try:
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise ValueError("Tool result must be finite JSON-serializable data") from None
        if len(encoded) > self._max_output_bytes:
            raise ValueError("Tool result exceeds configured output limit")
        return json.loads(encoded.decode("utf-8"))
