"""Tests for 예실대비표 normalization and budget-specific query handling."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from agent.executor import run
from agent.intent_utils import prepend_exclude_summary
from agent.router import route_query
from core.budget_table_normalizer import (
    OUTPUT_COLUMNS,
    is_specialized_domain_sheet,
    normalize_budget_sheet,
)
from core.profiler import profile_dataframe
from core.reader import load_excel


def _raw_budget_fixture() -> pd.DataFrame:
    """Minimal 2-row-header 예실대비표-like sheet (header=None shape)."""
    return pd.DataFrame(
        [
            [
                "비목분류",
                "",
                "비용명",
                "계획예산",
                "실행예산",
                "실행예산",
                "실행예산",
                "전년도집행",
                "당년도예산",
                "당년도집행",
                "가집행금액",
                "당해누계",
                "집행계",
                "집행계",
                "집행계",
                "예산잔액",
                "예산잔액",
                "예산잔액",
            ],
            [
                "",
                "",
                "",
                "",
                "이월예산",
                "당해예산",
                "합계",
                "",
                "",
                "",
                "",
                "",
                "이월집행",
                "당해집행",
                "합계",
                "이월잔액",
                "당해잔액",
                "합계",
            ],
            ["연구개발비", "30101", "인쇄비", 1000, 100, 200, 300, 50, 3000000, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            ["", "30102", "회의비   ", 2000, 200, 400, 600, 100, 5000000, 1000, 0, 500, 0, 500, 500, 0, 4500, 4500],
            ["소 계", "", "", 3000, 300, 600, 900, 150, "8,000,000", 1000, 0, 500, 0, 500, 500, 0, 4500, 4500],
            ["합         계", "", "", 3000, 300, 600, 900, 150, "150,000,000", 1000, 0, 500, 0, 500, 500, 0, 4500, 4500],
        ]
    )


@pytest.fixture
def raw_budget_df() -> pd.DataFrame:
    return _raw_budget_fixture()


@pytest.fixture
def normalized_budget_df(raw_budget_df: pd.DataFrame) -> pd.DataFrame:
    return normalize_budget_sheet(raw_budget_df)


@pytest.fixture
def normalized_budget_profile(normalized_budget_df: pd.DataFrame) -> dict:
    return profile_dataframe(normalized_budget_df)


@pytest.fixture
def budget_xlsx(tmp_path, raw_budget_df: pd.DataFrame) -> str:
    path = tmp_path / "yesil.xlsx"
    raw_budget_df.to_excel(path, index=False, header=False)
    return str(path)


# --- detection / normalization ---


def test_is_specialized_domain_sheet_detects_pattern(raw_budget_df: pd.DataFrame) -> None:
    assert is_specialized_domain_sheet(raw_budget_df) is True


def test_normalize_budget_sheet_column_names(normalized_budget_df: pd.DataFrame) -> None:
    assert list(normalized_budget_df.columns) == OUTPUT_COLUMNS
    assert not any(str(c).startswith("Unnamed") for c in normalized_budget_df.columns)


def test_normalize_budget_sheet_forward_fill_category(normalized_budget_df: pd.DataFrame) -> None:
    meeting = normalized_budget_df[normalized_budget_df["비용명"].str.contains("회의비", na=False)]
    assert not meeting.empty
    assert meeting.iloc[0]["비목분류"] == "연구개발비"


def test_normalize_budget_sheet_code_and_name_columns(normalized_budget_df: pd.DataFrame) -> None:
    printing = normalized_budget_df[normalized_budget_df["비용명"] == "인쇄비"].iloc[0]
    assert printing["비목코드"] == "30101"
    assert printing["비용명"] == "인쇄비"


def test_normalize_budget_sheet_subtotal_row_type(normalized_budget_df: pd.DataFrame) -> None:
    subtotal = normalized_budget_df[normalized_budget_df["행구분"] == "소계"]
    assert len(subtotal) == 1
    assert subtotal.iloc[0]["비목분류"] == "연구개발비"


def test_normalize_budget_sheet_total_row_type(normalized_budget_df: pd.DataFrame) -> None:
    total = normalized_budget_df[normalized_budget_df["행구분"] == "합계"]
    assert len(total) == 1


def test_normalize_budget_sheet_comma_amounts(normalized_budget_df: pd.DataFrame) -> None:
    total = normalized_budget_df[normalized_budget_df["행구분"] == "합계"].iloc[0]
    assert total["당년도예산"] == 150_000_000


def test_normalize_budget_sheet_trims_cost_name(normalized_budget_df: pd.DataFrame) -> None:
    meeting = normalized_budget_df[normalized_budget_df["비용명"] == "회의비"]
    assert len(meeting) == 1


def test_load_excel_normalizes_budget_sheet(budget_xlsx: str) -> None:
    df = load_excel(budget_xlsx)
    assert "행구분" in df.columns
    assert "비목코드" in df.columns
    assert df["비용명"].str.contains("인쇄비", na=False).any()


# --- routing / intent ---


def test_route_top_n_uses_top_n_not_aggregate(normalized_budget_profile: dict) -> None:
    intent = route_query("당해예산 중에 가장 높은 값인 행을 찾아줘", normalized_budget_profile)
    assert intent["operations"][0]["type"] == "top_n"
    assert intent["operations"][0]["type"] != "aggregate"


def test_route_value_answer_printing(normalized_budget_profile: dict) -> None:
    intent = route_query("인쇄비가 얼마지", normalized_budget_profile)
    assert intent["operations"][0]["type"] == "value_answer"
    assert intent["operations"][0]["row_query"] == "인쇄비"


def test_prepend_filter_row_type_for_top_n(normalized_budget_profile: dict) -> None:
    intent = route_query("당해예산 중에 가장 높은 값인 행을 찾아줘", normalized_budget_profile)
    intent = prepend_exclude_summary(intent, "당해예산 중에 가장 높은 값인 행을 찾아줘", normalized_budget_profile)
    assert intent["operations"][0]["type"] == "filter_row_type"
    assert intent["operations"][0]["row_types"] == ["상세"]
    assert intent["operations"][1]["type"] == "top_n"


def test_describe_returns_message_not_empty_ops(normalized_budget_profile: dict) -> None:
    intent = route_query("데이터에 대해서 설명", normalized_budget_profile)
    assert intent["operations"] == [{"type": "describe_dataset"}]
    from agent.response_formatter import format_user_response
    from core.budget_table_normalizer import normalize_budget_sheet
    from tests.test_budget_normalizer import _raw_budget_fixture

    df = normalize_budget_sheet(_raw_budget_fixture())
    message, _, _ = format_user_response(
        "데이터에 대해서 설명",
        intent,
        {"df": df, "debug_logs": [], "resolved_columns": {}, "value_metadata": {}},
        normalized_budget_profile,
    )
    assert message
    assert "예실대비표" in message


# --- executor e2e ---


@patch("llm.intent.chat")
def test_executor_top_n_excludes_total_row(mock_chat, budget_xlsx: str) -> None:
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_xlsx, "당해예산 중에 가장 높은 값인 행을 찾아줘")
    assert result["success"]
    assert result["df"]["비용명"].iloc[0] == "회의비"
    assert result["df"]["당년도예산"].iloc[0] == 5_000_000
    assert "당년도예산" in result["message"]


@patch("llm.intent.chat")
def test_executor_value_answer_printing(mock_chat, budget_xlsx: str) -> None:
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_xlsx, "인쇄비가 얼마지")
    assert result["success"]
    assert "인쇄비" in result["message"]
    assert result["df"] is not None


@patch("llm.intent.chat")
def test_executor_total_row(mock_chat, budget_xlsx: str) -> None:
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_xlsx, "전체 합계 알려줘")
    assert result["success"]
    assert len(result["df"]) == 1
    assert result["raw_df"]["행구분"].iloc[0] == "합계"


@patch("llm.intent.chat")
def test_executor_remaining_balance(mock_chat, budget_xlsx: str) -> None:
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_xlsx, "예산잔액이 남은 항목만 보여줘")
    assert result["success"]
    assert len(result["df"]) >= 1
    assert (result["df"]["예산잔액_당해잔액"] > 0).all()


@patch("llm.intent.chat")
def test_executor_top5_execution(mock_chat, budget_xlsx: str) -> None:
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_xlsx, "당년도집행이 가장 큰 항목 5개 보여줘")
    assert result["success"]
    assert len(result["df"]) <= 2


def test_generate_response_describe_budget(normalized_budget_df, normalized_budget_profile):
    from agent.response_formatter import format_user_response

    execution = {
        "df": normalized_budget_df,
        "debug_logs": [],
        "resolved_columns": {},
        "value_metadata": {},
    }
    intent = {"operations": [{"type": "describe_dataset"}]}
    msg, _, _ = format_user_response(
        "데이터에 대해서 설명", intent, execution, normalized_budget_profile
    )
    assert msg
    assert "예실대비표" in msg
