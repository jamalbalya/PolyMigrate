"""Minimal standard-library HTTP adapters for common LLM APIs.

Tool calling is intentionally not advertised in this milestone. The agent runtime
must not assume that text generation alone can execute tools safely.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from polymigrate.ai.protocols import ModelRequest, ModelResponse, ProviderCapabilities


class ProviderRequestError(RuntimeError):
    """Sanitized provider error that never includes credentials or request headers."""


def _validate_base_url(base_url: str) -> None:
    try:
        parsed = urlparse(base_url)
        hostname = parsed.hostname
        # Accessing .port forces urllib's otherwise-lazy port validation.
        parsed.port
    except (TypeError, ValueError):
        raise ValueError("base_url must be a valid URL with a valid port") from None
    if not hostname or parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must include a hostname and must not embed credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not include a query string or fragment")
    if parsed.scheme == "https":
        return
    if parsed.scheme == "http" and hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        return
    raise ValueError("base_url must use HTTPS; HTTP is permitted only for loopback test/local endpoints")



def _validate_provider_limits(timeout: float, max_output_tokens: int) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a finite positive number")
    if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or not 1 <= max_output_tokens <= 16_384:
        raise ValueError("max_output_tokens must be an integer between 1 and 16384")


def _prompt(request: ModelRequest) -> str:
    context = json.dumps(request.context, sort_keys=True, ensure_ascii=False)
    prefix = "Return a valid JSON object only.\n" if request.require_structured_output else ""
    return f"{prefix}Task: {request.task}\nContext JSON:\n{context}\n\nInstructions:\n{request.prompt}"


def _request_json(url: str, headers: dict[str, str], payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = {**headers, **({"Content-Type": "application/json"} if body is not None else {})}
    request = urllib.request.Request(url, data=body, headers=request_headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read(2_000_001)
        if len(response_body) > 2_000_000:
            raise ProviderRequestError("LLM provider response exceeded the 2 MB safety limit")
        data = json.loads(response_body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderRequestError(f"LLM provider returned HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        reason_type = type(reason).__name__ if reason is not None else "UnknownNetworkError"
        raise ProviderRequestError(f"LLM provider request failed ({reason_type})") from None
    except (TimeoutError, json.JSONDecodeError, UnicodeError, OSError) as exc:
        raise ProviderRequestError(f"LLM provider response failed ({type(exc).__name__})") from None
    if not isinstance(data, dict):
        raise ProviderRequestError("LLM provider returned a non-object JSON response")
    return data


def _parse_json_content(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass
class OpenAICompatibleProvider:
    """Adapter for OpenAI Chat Completions-compatible APIs, including compatible routers."""
    provider_id: str
    api_key: str
    model_id: str
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 60.0
    max_output_tokens: int = 8192

    def __post_init__(self) -> None:
        self.provider_id = self.provider_id.strip().lower()
        self.base_url = self.base_url.rstrip("/")
        _validate_base_url(self.base_url)
        if not self.provider_id or not self.api_key:
            raise ValueError("provider_id and api_key are required")
        _validate_provider_limits(self.timeout, self.max_output_tokens)

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(structured_output=True, tool_calling=False, streaming=False)

    def list_models(self) -> tuple[str, ...]:
        """Return model IDs exposed by the OpenAI-compatible endpoint without logging credentials."""
        data = _request_json(f"{self.base_url}/models", {"Authorization": f"Bearer {self.api_key}"}, None, self.timeout)
        entries = data.get("data")
        if not isinstance(entries, list):
            raise ProviderRequestError("LLM provider model catalogue is missing data list")
        model_ids = sorted({item["id"] for item in entries if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]})
        if not model_ids:
            raise ProviderRequestError("LLM provider model catalogue contained no model IDs")
        return tuple(model_ids)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if not self.model_id.strip():
            raise ProviderRequestError(
                f"{self.provider_id} model is not configured; run 'polymigrate providers --list-models' and set the model ID"
            )
        token_limit_key = "max_completion_tokens" if self.provider_id == "openai" else "max_tokens"
        payload: dict[str, Any] = {"model": self.model_id, "messages": [{"role": "user", "content": _prompt(request)}],
                                   token_limit_key: self.max_output_tokens}
        if request.require_structured_output:
            payload["response_format"] = {"type": "json_object"}
        data = _request_json(f"{self.base_url}/chat/completions",
                             {"Authorization": f"Bearer {self.api_key}"}, payload, self.timeout)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderRequestError("LLM provider response is missing choices[0].message.content") from None
        if isinstance(content, list):
            content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        if not isinstance(content, str):
            raise ProviderRequestError("LLM provider content is not text")
        structured = _parse_json_content(content) if request.require_structured_output else None
        if request.require_structured_output and structured is None:
            raise ProviderRequestError("LLM provider did not return a valid JSON object as requested")
        return ModelResponse(content, self.provider_id, self.model_id, structured)


@dataclass
class AnthropicProvider:
    """Adapter for Anthropic Messages API; structured output is not advertised here."""
    api_key: str
    model_id: str
    base_url: str = "https://api.anthropic.com/v1"
    timeout: float = 60.0
    provider_id: str = "anthropic"
    max_output_tokens: int = 8192

    def __post_init__(self) -> None:
        if not self.api_key or not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("api_key and model_id are required")
        self.base_url = self.base_url.rstrip("/")
        _validate_base_url(self.base_url)
        _validate_provider_limits(self.timeout, self.max_output_tokens)

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(structured_output=False, tool_calling=False, streaming=False)

    def generate(self, request: ModelRequest) -> ModelResponse:
        if request.require_structured_output or request.require_tool_calling:
            raise ProviderRequestError("Anthropic adapter does not advertise the requested capability in this release")
        data = _request_json(
            f"{self.base_url}/messages",
            {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            {"model": self.model_id, "max_tokens": self.max_output_tokens, "messages": [{"role": "user", "content": _prompt(request)}]},
            self.timeout)
        try:
            content = "".join(item.get("text", "") for item in data["content"] if item.get("type") == "text")
        except (KeyError, TypeError, AttributeError):
            raise ProviderRequestError("Anthropic response is missing text content") from None
        if not content:
            raise ProviderRequestError("Anthropic response contained no text content")
        return ModelResponse(content, self.provider_id, self.model_id)


@dataclass
class GeminiProvider:
    """Adapter for Gemini generateContent API."""
    api_key: str
    model_id: str
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    timeout: float = 60.0
    provider_id: str = "gemini"
    max_output_tokens: int = 8192

    def __post_init__(self) -> None:
        if not self.api_key or not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ValueError("api_key and model_id are required")
        self.base_url = self.base_url.rstrip("/")
        _validate_base_url(self.base_url)
        _validate_provider_limits(self.timeout, self.max_output_tokens)

    def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(structured_output=True, tool_calling=False, streaming=False)

    def generate(self, request: ModelRequest) -> ModelResponse:
        generation_config: dict[str, Any] = {"maxOutputTokens": self.max_output_tokens}
        if request.require_structured_output:
            generation_config["responseMimeType"] = "application/json"
        data = _request_json(
            f"{self.base_url}/models/{urllib.parse.quote(self.model_id, safe='')}:generateContent",
            {"x-goog-api-key": self.api_key},
            {"contents": [{"role": "user", "parts": [{"text": _prompt(request)}]}],
             **({"generationConfig": generation_config} if generation_config else {})},
            self.timeout)
        try:
            content = "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ProviderRequestError("Gemini response is missing candidate text content") from None
        if not content:
            raise ProviderRequestError("Gemini response contained no text content")
        structured = _parse_json_content(content) if request.require_structured_output else None
        if request.require_structured_output and structured is None:
            raise ProviderRequestError("Gemini did not return a valid JSON object as requested")
        return ModelResponse(content, self.provider_id, self.model_id, structured)
