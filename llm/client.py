"""Ollama client — thin wrapper around the Ollama chat API."""

from __future__ import annotations

import os

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")


class OllamaConnectionError(ConnectionError):
    """Raised when the Ollama server cannot be reached."""


class OllamaModelNotFoundError(LookupError):
    """Raised when the requested Ollama model is not installed."""


def chat(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
) -> str:
    """Send a chat request to a local Ollama model.

    Args:
        system_prompt: System instruction for the model.
        user_message: User message text.
        model: Ollama model name (default: OLLAMA_MODEL env or qwen2.5:7b).

    Returns:
        Assistant response text.

    Raises:
        OllamaConnectionError: If the Ollama server is unreachable.
        OllamaModelNotFoundError: If the model is not installed locally.
    """
    resolved_model = model or DEFAULT_MODEL
    try:
        return _chat_via_ollama_lib(system_prompt, user_message, resolved_model)
    except ImportError:
        return _chat_via_requests(system_prompt, user_message, resolved_model)


def _chat_via_ollama_lib(system_prompt: str, user_message: str, model: str) -> str:
    import ollama

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception as exc:
        raise _wrap_ollama_error(exc, model) from exc

    return response["message"]["content"]


def _chat_via_requests(system_prompt: str, user_message: str, model: str) -> str:
    import requests

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
    }

    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise OllamaConnectionError(
            "Ollama 서버에 연결할 수 없습니다. "
            "Ollama가 실행 중인지 확인하세요 (http://localhost:11434)."
        ) from exc
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise _model_not_found_error(model) from exc
        raise OllamaConnectionError(f"Ollama API 호출 실패: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise OllamaConnectionError(f"Ollama API 호출 실패: {exc}") from exc

    data = response.json()
    return data["message"]["content"]


def _wrap_ollama_error(exc: Exception, model: str) -> Exception:
    message = str(exc).lower()
    if "not found" in message or "status code: 404" in message:
        return _model_not_found_error(model)
    if any(
        token in message
        for token in ("connection", "refused", "unreachable", "connect")
    ):
        return OllamaConnectionError(
            "Ollama 서버에 연결할 수 없습니다. "
            "Ollama가 실행 중인지 확인하세요 (http://localhost:11434)."
        )
    return OllamaConnectionError(f"Ollama API 호출 실패: {exc}")


def _model_not_found_error(model: str) -> OllamaModelNotFoundError:
    return OllamaModelNotFoundError(
        f"Ollama 모델 '{model}'을(를) 찾을 수 없습니다. "
        f"'ollama pull {model}' 로 설치하거나 "
        f"OLLAMA_MODEL 환경변수로 설치된 모델을 지정하세요."
    )
