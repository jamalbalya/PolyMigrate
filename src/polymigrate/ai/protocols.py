"""Provider interfaces intentionally independent of vendor SDKs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderCapabilities:
    structured_output: bool = False
    tool_calling: bool = False
    streaming: bool = False
    max_context_tokens: int | None = None


@dataclass(frozen=True)
class ModelRequest:
    task: str
    prompt: str
    context: dict[str, Any]
    require_structured_output: bool = False
    require_tool_calling: bool = False


@dataclass(frozen=True)
class ModelResponse:
    content: str
    provider_id: str
    model_id: str
    structured_data: dict[str, Any] | None = None


class AIProvider(Protocol):
    provider_id: str

    def get_capabilities(self) -> ProviderCapabilities: ...
    def generate(self, request: ModelRequest) -> ModelResponse: ...
