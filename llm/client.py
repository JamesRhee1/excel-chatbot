"""Ollama client — thin wrapper around the Ollama chat API."""

from __future__ import annotations

import os

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
CHAT_OPTIONS = {"format": "json", "options": {"temperature": 0}}


class OllamaConnectionError(ConnectionError):
    """Raised when the Ollama server cannot be reached."""


class OllamaModelNotFoundError(LookupError):
    """Raised when the requested Ollama model is not installed."""


def chat(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
) -> str:
    """Send a chat request expecting JSON-formatted output."""
    resolved_model = model or DEFAULT_MODEL
    try:
        return _chat_via_ollama_lib(system_prompt, user_message, resolved_model)
    except ImportError:
        return _chat_via_requests(system_prompt, user_message, resolved_model)


def chat_plain(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
) -> str:
    """Send a chat request expecting plain-text output."""
    resolved_model = model or DEFAULT_MODEL
    try:
        return _chat_plain_via_ollama_lib(system_prompt, user_message, resolved_model)
    except ImportError:
        return _chat_plain_via_requests(system_prompt, user_message, resolved_model)


def _chat_plain_via_ollama_lib(system_prompt: str, user_message: str, model: str) -> str:
    import ollama

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            options={"temperature": 0},
        )
    except Exception as exc:
        raise _wrap_ollama_error(exc, model) from exc

    return response["message"]["content"]


def _chat_plain_via_requests(system_prompt: str, user_message: str, model: str) -> str:
    import requests

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "stream": False,
        "options": {"temperature": 0},
    }

    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise OllamaConnectionError(
            "Ollama 서버에 연결할 수 없습니다. "
            "터미널에서 'ollama serve'가 실행 중인지 확인하세요."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise OllamaConnectionError(
            "Ollama 서버 응답 시간이 초과되었습니다. "
            "서버가 실행 중인지 확인하거나 더 작은 모델을 사용해 보세요."
        ) from exc
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            raise _model_not_found_error(model) from exc
        raise OllamaConnectionError(f"Ollama API 호출 실패: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise OllamaConnectionError(f"Ollama API 호출 실패: {exc}") from exc

    data = response.json()
    return data["message"]["content"]


def _chat_via_ollama_lib(system_prompt: str, user_message: str, model: str) -> str:
    import ollama

    try:
        response = ollama.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            format="json",
            options={"temperature": 0},
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
        "format": "json",
        "options": {"temperature": 0},
    }

    try:
        response = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=120)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise OllamaConnectionError(
            "Ollama 서버에 연결할 수 없습니다. "
            "터미널에서 'ollama serve'가 실행 중인지 확인하세요."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise OllamaConnectionError(
            "Ollama 서버 응답 시간이 초과되었습니다. "
            "서버가 실행 중인지 확인하거나 더 작은 모델을 사용해 보세요."
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
    if "timeout" in message or "timed out" in message:
        return OllamaConnectionError(
            "Ollama 서버 응답 시간이 초과되었습니다. "
            "서버가 실행 중인지 확인하거나 더 작은 모델을 사용해 보세요."
        )
    if any(
        token in message
        for token in ("connection", "refused", "unreachable", "connect")
    ):
        return OllamaConnectionError(
            "Ollama 서버에 연결할 수 없습니다. "
            "터미널에서 'ollama serve'가 실행 중인지 확인하세요."
        )
    return OllamaConnectionError(f"Ollama API 호출 실패: {exc}")


def _model_not_found_error(model: str) -> OllamaModelNotFoundError:
    return OllamaModelNotFoundError(
        f"Ollama 모델 '{model}'이(가) 설치되어 있지 않습니다. "
        f"터미널에서 'ollama pull {model}' 명령으로 설치하거나 "
        f"사이드바에서 설치된 다른 모델을 선택하세요."
    )
