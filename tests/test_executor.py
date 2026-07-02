"""Tests for agent.executor.run() — structured results and error handling."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from agent.executor import run
from llm.client import OllamaConnectionError, OllamaModelNotFoundError
from llm.intent import IntentParseError


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


@patch("agent.executor.parse_intent")
def test_run_passes_model_to_parse_intent(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.return_value = {"operations": [], "message": ""}

    result = run(sample_excel, "정렬해줘", model="qwen3:8b", dry_run=True)

    assert result["success"] is True
    mock_parse_intent.assert_called_once()
    _, kwargs = mock_parse_intent.call_args
    assert kwargs.get("model") == "qwen3:8b"


@patch("agent.executor.parse_intent")
def test_run_dry_run_returns_operations_only(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.return_value = {
        "operations": [{"type": "select", "columns": ["이름", "매출"]}]
    }

    result = run(sample_excel, "이름과 매출만", dry_run=True)

    assert result["success"] is True
    assert result["df"] is None
    assert result["operations"] == [{"type": "select", "columns": ["이름", "매출"]}]
    assert result["saved_path"] is None
    assert result["backup_path"] is None
    assert result["error"] is None


@patch("agent.executor.save_excel")
@patch("agent.executor.parse_intent")
def test_run_saves_when_output_path_given(
    mock_parse_intent,
    mock_save_excel,
    sample_excel: str,
    tmp_path,
) -> None:
    mock_parse_intent.return_value = {
        "operations": [{"type": "filter", "column": "매출", "op": ">", "value": 500}]
    }
    output_path = str(tmp_path / "output.xlsx")
    mock_save_excel.return_value = output_path

    result = run(sample_excel, "매출 500 이상", output_path=output_path)

    assert result["success"] is True
    mock_save_excel.assert_called_once()
    call_df, call_path = mock_save_excel.call_args[0]
    assert call_path == output_path
    assert len(call_df) == 3
    assert mock_save_excel.call_args.kwargs["backup"] is True
    assert result["saved_path"] == output_path
    assert result["backup_path"] is None


@patch("agent.executor.parse_intent")
def test_run_missing_column_returns_korean_error(
    mock_parse_intent, sample_excel: str
) -> None:
    mock_parse_intent.return_value = {
        "operations": [{"type": "filter", "column": "존재하지않는컬럼", "op": ">", "value": 1000}]
    }

    result = run(sample_excel, "존재하지않는컬럼 1000 이상")

    assert result["success"] is False
    assert result["df"] is None
    assert "존재하지않는컬럼" in result["error"] or "찾을 수 없" in result["error"]


@patch("agent.executor.parse_intent")
def test_run_unsupported_operation_type(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.return_value = {"operations": [{"type": "pivot"}]}

    result = run(sample_excel, "피벗 테이블")

    assert result["success"] is False
    assert "지원하지 않는 operation type" in result["error"]


@patch("agent.executor.parse_intent")
def test_run_intent_parse_error(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.side_effect = IntentParseError('의도 JSON에 "operations" 키가 없습니다.')

    result = run(sample_excel, "알 수 없는 요청")

    assert result["success"] is False
    assert "operations" in result["error"]


@patch("agent.executor.parse_intent")
def test_run_ollama_connection_error(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.side_effect = OllamaConnectionError(
        "Ollama 서버에 연결할 수 없습니다."
    )

    result = run(sample_excel, "정렬해줘")

    assert result["success"] is False
    assert "Ollama 서버" in result["error"]


@patch("agent.executor.parse_intent")
def test_run_ollama_model_not_found(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.side_effect = OllamaModelNotFoundError(
        "Ollama 모델 'qwen2.5'을(를) 찾을 수 없습니다."
    )

    result = run(sample_excel, "정렬해줘")

    assert result["success"] is False
    assert "찾을 수 없습니다" in result["error"]


@patch("agent.executor.parse_intent")
def test_run_success_returns_dataframe(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.return_value = {
        "operations": [{"type": "filter", "column": "매출", "op": ">", "value": 1500}]
    }

    result = run(sample_excel, "매출 1500 이상")

    assert result["success"] is True
    assert len(result["df"]) == 1
    assert result["df"]["매출"].iloc[0] == 2500
    assert result["error"] is None
