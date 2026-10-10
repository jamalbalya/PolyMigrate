"""Capability-aware provider registry."""
from __future__ import annotations

from .protocols import AIProvider, ModelRequest


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderCapabilityError(RuntimeError):
    pass


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register(self, provider: AIProvider) -> None:
        provider_id = provider.provider_id.strip().lower()
        if not provider_id or provider_id != provider.provider_id:
            raise ValueError("Provider id must be non-empty lowercase canonical text")
        if provider_id in self._providers:
            raise ValueError(f"Provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def get(self, provider_id: str) -> AIProvider:
        try:
            return self._providers[provider_id.strip().lower()]
        except KeyError as exc:
            raise ProviderUnavailableError(f"AI provider '{provider_id}' is not configured") from exc

    def generate(self, provider_id: str, request: ModelRequest):
        provider = self.get(provider_id)
        capabilities = provider.get_capabilities()
        if request.require_structured_output and not capabilities.structured_output:
            raise ProviderCapabilityError(f"Provider '{provider_id}' does not support required structured output")
        if request.require_tool_calling and not capabilities.tool_calling:
            raise ProviderCapabilityError(f"Provider '{provider_id}' does not support required tool calling")
        return provider.generate(request)
