"""Environment-based provider configuration without reading or logging secret values."""
from __future__ import annotations

import os
from collections.abc import Mapping

from polymigrate.ai.http_providers import AnthropicProvider, GeminiProvider, OpenAICompatibleProvider
from polymigrate.ai.registry import ProviderRegistry


def build_provider_registry(environ: Mapping[str, str] | None = None) -> tuple[ProviderRegistry, tuple[str, ...]]:
    """Build a registry from environment variables and return non-secret configuration warnings.

    Model IDs are explicit environment settings so defaults do not silently become stale.
    Providers are only registered when both the API key and model ID are present.
    """
    env = environ if environ is not None else os.environ
    registry = ProviderRegistry()
    warnings: list[str] = []

    definitions = (
        ("OPENAI_API_KEY", "OPENAI_MODEL", "openai"),
        ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "openrouter"),
        ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "anthropic"),
        ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini"),
    )
    for key_name, model_name, provider_id in definitions:
        api_key = env.get(key_name, "").strip()
        model_id = env.get(model_name, "").strip()
        if not api_key and not model_id:
            continue
        if not api_key:
            warnings.append(f"{provider_id}: {key_name} is not configured")
            continue
        if not model_id:
            warnings.append(f"{provider_id}: {model_name} is not configured")
            continue
        if provider_id == "openai":
            provider = OpenAICompatibleProvider(
                provider_id="openai", api_key=api_key, model_id=model_id,
                base_url=env.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            )
        elif provider_id == "openrouter":
            provider = OpenAICompatibleProvider(
                provider_id="openrouter", api_key=api_key, model_id=model_id,
                base_url=env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            )
        elif provider_id == "anthropic":
            provider = AnthropicProvider(api_key=api_key, model_id=model_id,
                                         base_url=env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"))
        else:
            provider = GeminiProvider(api_key=api_key, model_id=model_id,
                                      base_url=env.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"))
        registry.register(provider)
    return registry, tuple(warnings)
