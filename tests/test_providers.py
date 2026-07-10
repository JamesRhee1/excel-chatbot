"""Tests for LLM provider selection and demo-mode behavior."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from llm.intent import demo_mode_llm_message
from llm.providers import (
    GeminiProvider,
    OllamaProvider,
    get_provider,
    is_llm_available,
    reset_provider_cache,
)


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    reset_provider_cache()
    yield
    reset_provider_cache()


def test_forced_ollama_provider(monkeypatch):
    monkeypatch.setenv("EXCEL_CHATBOT_LLM_PROVIDER", "ollama")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    provider = get_provider()

    assert provider is not None
    assert provider.name == "ollama"
    assert isinstance(provider, OllamaProvider)


def test_forced_gemini_provider(monkeypatch):
    monkeypatch.setenv("EXCEL_CHATBOT_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    provider = get_provider()

    assert provider is not None
    assert provider.name == "gemini"
    assert isinstance(provider, GeminiProvider)


def test_auto_select_ollama_when_available(monkeypatch):
    monkeypatch.delenv("EXCEL_CHATBOT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with patch.object(OllamaProvider, "is_available", return_value=True):
        provider = get_provider()

    assert provider is not None
    assert provider.name == "ollama"


def test_auto_select_gemini_when_ollama_down(monkeypatch):
    monkeypatch.delenv("EXCEL_CHATBOT_LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    with patch.object(OllamaProvider, "is_available", return_value=False):
        provider = get_provider()

    assert provider is not None
    assert provider.name == "gemini"


def test_no_provider_demo_mode(monkeypatch):
    monkeypatch.delenv("EXCEL_CHATBOT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with patch.object(OllamaProvider, "is_available", return_value=False):
        assert get_provider() is None
        assert is_llm_available() is False


def test_gemini_is_available_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiProvider().is_available() is False

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    assert GeminiProvider().is_available() is True


def test_demo_mode_llm_message_uses_domain_examples():
    profile = {"domain_example_queries": ["예산 대비 실적 비교", "부서별 합계"]}
    message = demo_mode_llm_message(profile)

    assert "데모 환경" in message
    assert "예산 대비 실적 비교" in message
    assert "부서별 합계" in message


@patch("ui.app.st")
def test_inject_secrets_to_env(mock_st, monkeypatch):
    from ui.app import _inject_secrets_to_env

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    mock_st.secrets = {"GEMINI_API_KEY": "from-secrets"}

    _inject_secrets_to_env()

    assert os.environ.get("GEMINI_API_KEY") == "from-secrets"


@patch("ui.app.st")
def test_inject_secrets_skips_when_env_already_set(mock_st, monkeypatch):
    from ui.app import _inject_secrets_to_env

    monkeypatch.setenv("GEMINI_API_KEY", "existing")
    mock_st.secrets = {"GEMINI_API_KEY": "from-secrets"}

    _inject_secrets_to_env()

    assert os.environ.get("GEMINI_API_KEY") == "existing"


@pytest.fixture
def sample_excel(tmp_path):
    import pandas as pd

    path = tmp_path / "sample.xlsx"
    pd.DataFrame({"이름": ["A"], "매출": [100]}).to_excel(path, index=False)
    return str(path)


@patch("agent.executor.parse_intent")
def test_executor_demo_mode_message(mock_parse_intent, sample_excel, monkeypatch):
    from agent.executor import run

    monkeypatch.delenv("EXCEL_CHATBOT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with patch.object(OllamaProvider, "is_available", return_value=False):
        result = run(sample_excel, "이 데이터를 자유롭게 해석해줘")

    mock_parse_intent.assert_not_called()
    assert result["success"] is True
    assert "데모 환경" in (result.get("message") or "")
    assert result.get("llm_provider") is None
