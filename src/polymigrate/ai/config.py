"""Environment-based provider configuration without reading or logging secret values."""
from __future__ import annotations

import os
from collections.abc import Mapping

from polymigrate.ai.http_providers import AnthropicProvider, GeminiProvider, OpenAICompatibleProvider
from polymigrate.ai.registry import ProviderRegistry


def _max_output_tokens(env: Mapping[str, str], key: str, warnings: list[str]) -> int:
    raw = env.get(key, "8192").strip()
    try:
        value = int(raw)
    except ValueError:
        warnings.append(f"{key} must be an integer; using the safe default of 8192")
        return 8192
    if not 1 <= value <= 16_384:
        warnings.append(f"{key} must be between 1 and 16384; using the safe default of 8192")
        return 8192
    return value


def build_provider_registry(environ: Mapping[str, str] | None = None) -> tuple[ProviderRegistry, tuple[str, ...]]:
    """Build a registry from environment variables and return non-secret configuration warnings.

    Model IDs are explicit environment settings so defaults do not silently become stale.
    Providers normally require an API key and model ID. The 9Router adapter is
    also registered with an empty model ID when only its API key is configured,
    allowing model discovery before the user selects a generation model.
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
    router_key = env.get("POLYMIGRATE_9ROUTER_API_KEY", "").strip()
    router_model = env.get("POLYMIGRATE_9ROUTER_MODEL", "").strip()
    if router_key or router_model:
        if not router_key:
            warnings.append("9router: POLYMIGRATE_9ROUTER_API_KEY is not configured")
        elif not router_model:
            warnings.append("9router: POLYMIGRATE_9ROUTER_MODEL is not configured; model discovery is available, generation is disabled")
            registry.register(OpenAICompatibleProvider(
                provider_id="9router", api_key=router_key, model_id="",
                base_url=env.get("POLYMIGRATE_9ROUTER_BASE_URL", "http://localhost:20128/v1"),
                max_output_tokens=_max_output_tokens(env, "POLYMIGRATE_9ROUTER_MAX_OUTPUT_TOKENS", warnings),
            ))
        else:
            registry.register(OpenAICompatibleProvider(
                provider_id="9router", api_key=router_key, model_id=router_model,
                base_url=env.get("POLYMIGRATE_9ROUTER_BASE_URL", "http://localhost:20128/v1"),
                max_output_tokens=_max_output_tokens(env, "POLYMIGRATE_9ROUTER_MAX_OUTPUT_TOKENS", warnings),
            ))

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
                max_output_tokens=_max_output_tokens(env, "OPENAI_MAX_OUTPUT_TOKENS", warnings),
            )
        elif provider_id == "openrouter":
            provider = OpenAICompatibleProvider(
                provider_id="openrouter", api_key=api_key, model_id=model_id,
                base_url=env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                max_output_tokens=_max_output_tokens(env, "OPENROUTER_MAX_OUTPUT_TOKENS", warnings),
            )
        elif provider_id == "anthropic":
            provider = AnthropicProvider(api_key=api_key, model_id=model_id,
                                         base_url=env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
                                         max_output_tokens=_max_output_tokens(env, "ANTHROPIC_MAX_OUTPUT_TOKENS", warnings))
        else:
            provider = GeminiProvider(api_key=api_key, model_id=model_id,
                                      base_url=env.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"),
                                      max_output_tokens=_max_output_tokens(env, "GEMINI_MAX_OUTPUT_TOKENS", warnings))
        registry.register(provider)
    return registry, tuple(warnings)
