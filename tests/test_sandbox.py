"""Tests for sandbox escape hatch (no LLM — fixed code strings)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pandas as pd
import pytest

from agent.executor import run
from core.sandbox_runner import SandboxError, is_codegen_enabled, run_sandbox, validate_code_static


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "이름": ["김철수", "이영희", "박민수"],
            "부서": ["영업", "개발", "영업"],
            "매출": [1000, 2500, 800],
        }
    )


@pytest.fixture
def sample_excel(tmp_path, sample_df: pd.DataFrame) -> str:
    path = tmp_path / "sample.xlsx"
    sample_df.to_excel(path, index=False)
    return str(path)


def test_codegen_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("EXCEL_CHATBOT_ENABLE_CODEGEN", raising=False)
    assert is_codegen_enabled() is False


@patch("agent.executor.parse_intent")
def test_flag_off_behaves_like_clarify(mock_parse_intent, sample_excel, monkeypatch) -> None:
    monkeypatch.delenv("EXCEL_CHATBOT_ENABLE_CODEGEN", raising=False)
    mock_parse_intent.return_value = {
        "answer_type": "message",
        "operations": [{"type": "clarify", "message": "다시 질문해 주세요."}],
        "message": "다시 질문해 주세요.",
    }
    result = run(sample_excel, "좀 정리해줘")
    assert result["success"]
    assert not result.get("codegen_pending")
    assert result["operations"][0]["type"] == "clarify"


def test_sandbox_normal_execution(sample_df: pd.DataFrame) -> None:
    code = "result = df.sort_values('매출', ascending=False).head(2)"
    output = run_sandbox(code, sample_df)
    assert len(output) == 2
    assert output.iloc[0]["매출"] == 2500


def test_sandbox_timeout(sample_df: pd.DataFrame) -> None:
    code = "x = 0\nwhile True:\n    x += 1"
    with pytest.raises(SandboxError, match="초과"):
        run_sandbox(code, sample_df, timeout=1)


def test_sandbox_rejects_dangerous_code(sample_df: pd.DataFrame) -> None:
    with pytest.raises(SandboxError):
        validate_code_static("import os\nresult = df")
    with pytest.raises(SandboxError):
        run_sandbox("import os\nresult = df", sample_df)


@patch("agent.executor.run_sandbox")
def test_approved_codegen_requires_flag(mock_run, sample_excel, monkeypatch) -> None:
    monkeypatch.delenv("EXCEL_CHATBOT_ENABLE_CODEGEN", raising=False)
    ws = None
    first = run(sample_excel, "도움말")
    ws = first["workspace"]
    result = run(
        user_message="test",
        workspace=ws,
        approved_codegen_code="result = df.head(1)",
    )
    assert not result["success"]
    mock_run.assert_not_called()


def test_approved_codegen_executes_with_flag(sample_excel, monkeypatch) -> None:
    monkeypatch.setenv("EXCEL_CHATBOT_ENABLE_CODEGEN", "1")
    first = run(sample_excel, "도움말")
    ws = first["workspace"]
    result = run(
        user_message="상위 1행",
        workspace=ws,
        approved_codegen_code="result = df.sort_values('매출', ascending=False).head(1)",
    )
    assert result["success"]
    assert result["route_path"] == "codegen"
    assert "LLM 생성 코드" in (result.get("message") or "")
    assert result.get("verification") == []
