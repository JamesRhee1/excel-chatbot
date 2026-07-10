"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_llm_available(request, monkeypatch):
    """CI has no Ollama; preserve legacy test behavior by assuming LLM is available."""
    if request.module.__name__.endswith("test_providers"):
        return
    monkeypatch.setattr("agent.executor.is_llm_available", lambda: True)
