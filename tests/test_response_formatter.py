"""Tests for concise user-facing response formatting."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from agent.executor import run
from agent.response_formatter import (
    format_user_response,
    is_internal_log,
    wants_full_detail,
)
from core.budget_table_normalizer import normalize_budget_sheet
from core.profiler import profile_dataframe


def _raw_budget_fixture() -> pd.DataFrame:
    from tests.test_budget_normalizer import _raw_budget_fixture as fixture

    return fixture()


@pytest.fixture
def normalized_budget_df():
    return normalize_budget_sheet(_raw_budget_fixture())


@pytest.fixture
def budget_xlsx(tmp_path):
    path = tmp_path / "yesil.xlsx"
    _raw_budget_fixture().to_excel(path, index=False, header=False)
    return str(path)


@pytest.fixture
def normalized_budget_profile(normalized_budget_df):
    return profile_dataframe(normalized_budget_df)


def _execution(df, *, value_metadata=None, debug_logs=None, resolved=None):
    return {
        "df": df,
        "debug_logs": debug_logs or [],
        "resolved_columns": resolved or {},
        "value_metadata": value_metadata or {},
        "applied": [],
    }


def test_wants_full_detail_keywords():
    assert wants_full_detail("전체 컬럼 보여줘") is True
    assert wants_full_detail("인쇄비가 얼마지") is False


def test_value_answer_message_is_concise(normalized_budget_df, normalized_budget_profile):
    printing = normalized_budget_df[normalized_budget_df["비용명"] == "인쇄비"].iloc[0]
    metadata = {
        "row_query": "인쇄비",
        "label": "인쇄비",
        "row": printing.to_dict(),
    }
    intent = {"operations": [{"type": "filter_row_type"}, {"type": "value_answer", "row_query": "인쇄비"}]}
    execution = _execution(
        normalized_budget_df.iloc[[0]],
        value_metadata=metadata,
        debug_logs=["행구분이 '상세'인 2개 행을 분석 대상으로 선정했습니다."],
    )

    message, display_df, raw_df = format_user_response(
        "인쇄비가 얼마지", intent, execution, normalized_budget_profile
    )

    assert not is_internal_log(message)
    assert "행구분" not in message
    assert "비목코드" not in message
    assert "당년도예산" in message
    assert "1,000,000원" in message or "3,000,000원" in message
    assert message.count("당년도예산") == 1
    assert display_df is not None
    assert "비목코드" not in display_df.columns
    assert raw_df is not None


def test_top_n_message_and_display_columns(normalized_budget_df, normalized_budget_profile):
    intent = {
        "operations": [
            {"type": "filter_row_type", "row_types": ["상세"]},
            {"type": "top_n", "column": "당해예산", "n": 1, "ascending": False},
        ]
    }
    top_df = normalized_budget_df[normalized_budget_df["행구분"] == "상세"].nlargest(1, "당년도예산")
    execution = _execution(
        top_df,
        resolved={"당해예산": "당년도예산"},
        debug_logs=["행구분이 '상세'인 2개 행을 분석 대상으로 선정했습니다."],
    )

    message, display_df, _ = format_user_response(
        "당해예산 중 가장 높은 행 찾아줘", intent, execution, normalized_budget_profile
    )

    assert "행구분" not in message
    assert "회의비" in message
    assert "비목코드" not in message
    assert display_df is not None
    assert "비용명" in display_df.columns
    assert "당년도예산" in display_df.columns
    assert len(display_df.columns) <= 6


def test_full_detail_shows_all_columns(normalized_budget_df, normalized_budget_profile):
    intent = {"operations": [{"type": "value_answer", "row_query": "인쇄비"}]}
    printing = normalized_budget_df[normalized_budget_df["비용명"] == "인쇄비"].iloc[0]
    execution = _execution(
        normalized_budget_df.iloc[[0]],
        value_metadata={"row_query": "인쇄비", "label": "인쇄비", "row": printing.to_dict()},
    )

    _, display_df, _ = format_user_response(
        "인쇄비 전체 컬럼 보여줘", intent, execution, normalized_budget_profile
    )
    assert display_df is not None
    assert len(display_df.columns) > 6


def test_filter_zero_rows_message(normalized_budget_df, normalized_budget_profile):
    intent = {
        "answer_type": "dataframe",
        "operations": [
            {"type": "filter_row_type", "row_types": ["상세"]},
            {"type": "filter", "column": "당년도예산", "op": ">", "value": 9_999_999_999},
        ],
    }
    empty = normalized_budget_df.iloc[0:0].copy()
    execution = {
        "df": empty,
        "resolved_columns": {"당년도예산": "당년도예산"},
        "debug_logs": [],
    }
    message, _, _ = format_user_response(
        "당년도예산 9999999999보다 큰 항목",
        intent,
        execution,
        normalized_budget_profile,
    )
    assert "조건에 맞는 행이 0건입니다" in message
    assert "당년도예산" in message
    assert "> 9999999999" in message or "> 9999999999.0" in message
    assert "질문을 조금 더 구체적으로" not in message


def test_lookup_empty_keeps_clarify_message(normalized_budget_df, normalized_budget_profile):
    intent = {
        "answer_type": "dataframe",
        "operations": [
            {"type": "filter_row_type", "row_types": ["상세"]},
            {"type": "lookup", "query": "없는항목xyz123"},
        ],
    }
    empty = normalized_budget_df.iloc[0:0].copy()
    execution = {"df": empty, "resolved_columns": {}, "debug_logs": []}
    message, _, _ = format_user_response(
        "없는항목xyz123 찾아줘",
        intent,
        execution,
        normalized_budget_profile,
    )
    assert "요청하신 조건에 맞는 데이터를 찾지 못했습니다" in message
    assert "질문을 조금 더 구체적으로" in message


def test_display_dataframe_resets_index(normalized_budget_df, normalized_budget_profile):
    intent = {"operations": [{"type": "sort", "column": "당년도예산", "ascending": False}]}
    sorted_df = normalized_budget_df.sort_values("당년도예산", ascending=False).head(2)
    execution = {"df": sorted_df, "resolved_columns": {}, "debug_logs": []}
    _, display_df, raw_df = format_user_response(
        "당년도예산 기준으로 정렬",
        intent,
        execution,
        normalized_budget_profile,
    )
    assert raw_df is not None
    assert display_df is not None
    assert raw_df.index.tolist() != [0, 1]
    assert display_df.index.tolist() == [0, 1]


def test_derive_top_n_message_summarizes_ratio(normalized_budget_df, normalized_budget_profile):
    working = normalized_budget_df[normalized_budget_df["행구분"] == "상세"].copy()
    working["수익률"] = working["당년도집행"] / working["당년도예산"]
    top_df = working.nlargest(1, "수익률")
    intent = {
        "operations": [
            {"type": "derive", "new_column": "수익률", "left": "당년도집행", "op": "divide", "right": "당년도예산"},
            {"type": "top_n", "column": "수익률", "n": 1, "ascending": False},
        ]
    }
    execution = {"df": top_df, "resolved_columns": {}, "debug_logs": []}
    message, _, _ = format_user_response(
        "수익률이 가장 높은 행",
        intent,
        execution,
        normalized_budget_profile,
    )
    assert message == "당년도집행/당년도예산 비율 기준 상위 1개입니다."


def test_derive_sort_message_summarizes_ratio(normalized_budget_df, normalized_budget_profile):
    working = normalized_budget_df[normalized_budget_df["행구분"] == "상세"].copy()
    working["수익률"] = working["당년도집행"] / working["당년도예산"]
    sorted_df = working.sort_values("수익률", ascending=False)
    intent = {
        "operations": [
            {"type": "derive", "new_column": "수익률", "left": "당년도집행", "op": "divide", "right": "당년도예산"},
            {"type": "sort", "column": "수익률", "ascending": False},
        ]
    }
    execution = {"df": sorted_df, "resolved_columns": {}, "debug_logs": []}
    message, _, _ = format_user_response(
        "수익률 기준 정렬",
        intent,
        execution,
        normalized_budget_profile,
    )
    assert message == "당년도집행/당년도예산 비율 기준 내림차순 정렬 결과입니다."


@patch("llm.intent.chat")
def test_executor_value_answer_no_internal_logs(mock_chat, budget_xlsx):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_xlsx, "인쇄비가 얼마지")
    assert result["success"]
    message = result["message"]
    assert "행구분" not in message
    assert "비목코드" not in message
    assert "당년도예산" in message
    assert message.count("당년도예산") <= 2
    assert result["df"] is not None
    assert "비목코드" not in result["df"].columns
    assert result.get("raw_df") is not None
    assert any("행구분" in log for log in result.get("debug_logs", []))


@patch("llm.intent.chat")
def test_executor_top_n_concise_message(mock_chat, budget_xlsx):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_xlsx, "당해예산 중 가장 높은 행 찾아줘")
    assert result["success"]
    assert "행구분" not in result["message"]
    assert result["df"] is not None
    assert len(result["df"].columns) <= 6
    assert result["raw_df"] is not None
    assert len(result["raw_df"].columns) > len(result["df"].columns)
