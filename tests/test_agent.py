"""Tests for llm and agent layers (mocked — no live Ollama required)."""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest

from agent.executor import run
from agent.tools import apply_operation
from llm.intent import IntentParseError, _extract_json, parse_intent


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Synthetic sales DataFrame."""
    return pd.DataFrame(
        {
            "이름": ["김철수", "이영희", "박민수", "최지연", "김철수"],
            "부서": ["영업", "개발", "영업", "개발", "마케팅"],
            "매출": [1000, 2500, 800, 3200, 1500],
            "연도": [2023, 2023, 2024, 2024, 2023],
        }
    )


@pytest.fixture
def sample_excel(tmp_path, sample_df: pd.DataFrame) -> str:
    """Write sample DataFrame to a temporary Excel file."""
    path = tmp_path / "sample.xlsx"
    sample_df.to_excel(path, index=False)
    return str(path)


# --- apply_operation ---


def test_apply_operation_filter(sample_df: pd.DataFrame) -> None:
    op = {"type": "filter", "column": "매출", "op": ">", "value": 1500}
    result = apply_operation(sample_df, op)
    assert len(result) == 2
    assert all(result["매출"] > 1500)


def test_apply_operation_sort(sample_df: pd.DataFrame) -> None:
    op = {"type": "sort", "column": "매출", "ascending": False}
    result = apply_operation(sample_df, op)
    assert result["매출"].tolist() == sorted(sample_df["매출"].tolist(), reverse=True)


def test_apply_operation_select(sample_df: pd.DataFrame) -> None:
    op = {"type": "select", "columns": ["이름", "매출"]}
    result = apply_operation(sample_df, op)
    assert list(result.columns) == ["이름", "매출"]


def test_apply_operation_aggregate(sample_df: pd.DataFrame) -> None:
    op = {
        "type": "aggregate",
        "group_by": ["부서"],
        "agg_column": "매출",
        "agg_func": "sum",
    }
    result = apply_operation(sample_df, op)
    assert "매출_sum" in result.columns
    assert len(result) == sample_df["부서"].nunique()


def test_apply_operation_unsupported_type(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="지원하지 않는 operation type"):
        apply_operation(sample_df, {"type": "pivot"})


# --- intent JSON extraction ---


def test_extract_json_plain() -> None:
    raw = '{"operations": [{"type": "filter", "column": "매출", "op": ">", "value": 1000}]}'
    result = _extract_json(raw)
    assert result["operations"][0]["type"] == "filter"


def test_extract_json_markdown_block() -> None:
    raw = '```json\n{"operations": []}\n```'
    result = _extract_json(raw)
    assert result == {"operations": []}


def test_extract_json_invalid_raises() -> None:
    with pytest.raises(IntentParseError, match="JSON"):
        _extract_json("이건 JSON이 아닙니다")


# --- parse_intent (mocked chat) ---


@patch("llm.intent.chat")
def test_parse_intent_success(mock_chat) -> None:
    intent = {
        "operations": [
            {"type": "filter", "column": "매출", "op": ">", "value": 1000},
            {"type": "sort", "column": "매출", "ascending": False},
        ]
    }
    mock_chat.return_value = json.dumps(intent, ensure_ascii=False)

    result = parse_intent("매출 1000 이상만 보여주고 내림차순 정렬", ["이름", "부서", "매출", "연도"])
    assert result == intent
    mock_chat.assert_called_once()


@patch("llm.intent.chat")
def test_parse_intent_missing_operations_raises(mock_chat) -> None:
    mock_chat.return_value = '{"action": "filter"}'
    with pytest.raises(IntentParseError, match="operations"):
        parse_intent("필터해줘", ["매출"])


# --- executor (mocked parse_intent) ---


@patch("agent.executor.parse_intent")
def test_executor_full_flow(mock_parse_intent, sample_excel: str, sample_df: pd.DataFrame) -> None:
    mock_parse_intent.return_value = {
        "operations": [
            {"type": "filter", "column": "매출", "op": ">", "value": 1500},
            {"type": "sort", "column": "매출", "ascending": True},
        ]
    }

    result = run(sample_excel, "매출 1500 이상 정렬해줘")

    assert result["success"] is True
    assert len(result["operations"]) == 2
    assert len(result["df"]) == 2
    assert result["df"]["매출"].tolist() == [2500, 3200]
    assert result["error"] is None


@patch("agent.executor.parse_intent")
def test_executor_dry_run(mock_parse_intent, sample_excel: str) -> None:
    intent = {
        "operations": [
            {"type": "select", "columns": ["이름", "매출"]},
        ]
    }
    mock_parse_intent.return_value = intent

    result = run(sample_excel, "이름과 매출만 보여줘", dry_run=True)

    assert result["success"] is True
    assert result["operations"] == intent["operations"]
    assert result["df"] is None
    assert result["error"] is None


@patch("agent.executor.parse_intent")
def test_executor_chained_operations(mock_parse_intent, sample_excel: str) -> None:
    mock_parse_intent.return_value = {
        "operations": [
            {"type": "filter", "column": "부서", "op": "==", "value": "영업"},
            {"type": "aggregate", "group_by": ["부서"], "agg_column": "매출", "agg_func": "sum"},
        ]
    }

    result = run(sample_excel, "영업 부서 매출 합계")

    assert result["success"] is True
    assert len(result["df"]) == 1
    assert result["df"]["매출_sum"].iloc[0] == 1800


# --- integration (requires live Ollama) ---


@pytest.mark.integration
def test_parse_intent_live_ollama() -> None:
    """Requires Ollama running with a chat model (default: qwen2.5:7b)."""
    import os

    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
    result = parse_intent(
        "매출 컬럼을 내림차순으로 정렬해줘",
        ["이름", "부서", "매출", "연도"],
        model=model,
    )
    assert "operations" in result
    assert isinstance(result["operations"], list)
    assert len(result["operations"]) >= 1
    assert result["operations"][0]["type"] == "sort"
