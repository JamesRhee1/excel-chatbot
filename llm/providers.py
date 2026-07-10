"""LLM provider abstraction: Ollama (local) with Gemini cloud fallback."""

from __future__ import annotations

import logging
import os
import time
from typing import Protocol, runtime_checkable

from llm.client import (
    OLLAMA_CHAT_URL,
    DEFAULT_MODEL,
    OllamaConnectionError,
    OllamaModelNotFoundError,
    _chat_plain_via_ollama_lib,
    _chat_plain_via_requests,
    _chat_via_ollama_lib,
    _chat_via_requests,
)

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
_provider_cache: tuple[float, LLMProvider | None] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def chat_json(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        ...

    def chat_plain(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        ...

    def is_available(self) -> bool:
        ...


class OllamaProvider:
    name = "ollama"

    def is_available(self) -> bool:
        import requests

        try:
            response = requests.get(
                OLLAMA_CHAT_URL.replace("/api/chat", "/api/tags"),
                timeout=2,
            )
            response.raise_for_status()
            return True
        except Exception:
            return False

    def chat_json(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        resolved_model = model or DEFAULT_MODEL
        try:
            return _chat_via_ollama_lib(system_prompt, user_message, resolved_model)
        except ImportError:
            return _chat_via_requests(system_prompt, user_message, resolved_model)

    def chat_plain(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        resolved_model = model or DEFAULT_MODEL
        try:
            return _chat_plain_via_ollama_lib(system_prompt, user_message, resolved_model)
        except ImportError:
            return _chat_plain_via_requests(system_prompt, user_message, resolved_model)


class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        self._default_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    def is_available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    def _model_name(self, model: str | None) -> str:
        if model and model.startswith("gemini"):
            return model
        return self._default_model

    def chat_json(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        genai = _import_genai()
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise OllamaConnectionError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
        genai.configure(api_key=api_key)
        gm = genai.GenerativeModel(
            self._model_name(model),
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        try:
            response = gm.generate_content(user_message)
        except Exception as exc:
            raise OllamaConnectionError(f"Gemini API 호출 실패: {exc}") from exc
        text = getattr(response, "text", None)
        if not text:
            raise OllamaConnectionError("Gemini API가 빈 응답을 반환했습니다.")
        return text

    def chat_plain(self, system_prompt: str, user_message: str, model: str | None = None) -> str:
        genai = _import_genai()
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise OllamaConnectionError("GEMINI_API_KEY가 설정되어 있지 않습니다.")
        genai.configure(api_key=api_key)
        gm = genai.GenerativeModel(
            self._model_name(model),
            system_instruction=system_prompt,
            generation_config=genai.GenerationConfig(temperature=0),
        )
        try:
            response = gm.generate_content(user_message)
        except Exception as exc:
            raise OllamaConnectionError(f"Gemini API 호출 실패: {exc}") from exc
        text = getattr(response, "text", None)
        if not text:
            raise OllamaConnectionError("Gemini API가 빈 응답을 반환했습니다.")
        return text


def _import_genai():
    try:
        import google.generativeai as genai
    except ImportError as exc:
        raise OllamaConnectionError(
            "google-generativeai 패키지가 설치되어 있지 않습니다. "
            'pip install -e ".[cloud]" 로 설치하세요.'
        ) from exc
    return genai


def _forced_provider_name() -> str | None:
    forced = os.environ.get("EXCEL_CHATBOT_LLM_PROVIDER", "").strip().lower()
    if forced in ("ollama", "gemini"):
        return forced
    return None


def _resolve_provider() -> LLMProvider | None:
    forced = _forced_provider_name()
    if forced == "ollama":
        return OllamaProvider()
    if forced == "gemini":
        return GeminiProvider()

    ollama = OllamaProvider()
    if ollama.is_available():
        return ollama

    gemini = GeminiProvider()
    if gemini.is_available():
        return gemini

    return None


def reset_provider_cache() -> None:
    global _provider_cache
    _provider_cache = None


def get_provider() -> LLMProvider | None:
    """Return the active LLM provider (cached 60s). None means demo mode."""
    global _provider_cache
    now = time.monotonic()
    if _provider_cache is not None and now - _provider_cache[0] < _CACHE_TTL_SECONDS:
        return _provider_cache[1]

    provider = _resolve_provider()
    _provider_cache = (now, provider)
    if provider is not None:
        logger.debug("LLM provider selected: %s", provider.name)
    else:
        logger.debug("No LLM provider available — demo mode")
    return provider


def is_llm_available() -> bool:
    return get_provider() is not None
