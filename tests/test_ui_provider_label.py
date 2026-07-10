"""Tests for LLM provider sidebar label mapping."""

from __future__ import annotations

from ui.app import llm_provider_sidebar_label


def test_sidebar_label_ollama() -> None:
    assert llm_provider_sidebar_label("ollama") == "LLM: Ollama (로컬)"


def test_sidebar_label_gemini() -> None:
    assert llm_provider_sidebar_label("gemini") == "LLM: Gemini (클라우드)"


def test_sidebar_label_demo_mode() -> None:
    assert llm_provider_sidebar_label(None) == "LLM: 비활성 (데모 모드)"
    assert llm_provider_sidebar_label("unknown") == "LLM: 비활성 (데모 모드)"
