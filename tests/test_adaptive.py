"""Tests for adaptive Excel analysis agent."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from agent.executor import run
from agent.router import route_query
from agent.tools import apply_operation
from core.column_resolver import resolve_column, suggest_columns
from core.profiler import profile_dataframe
from llm.intent import IntentParseError, _validate_intent, parse_intent


@pytest.fixture
def budget_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "비목분류": ["운영비", "장비비", "회의비"],
            "비용명": ["인쇄비", "서버구입비", "회의운영비"],
            "계획예산": [1000, 5000, 800],
            "실행예산": [900, 4800, 600],
            "전년도집행": [700, 4000, 500],
            "당년도예산": [1200, 7000, 900],
            "당년도집행": [800, 3000, 500],
            "가집행금액": [100, 200, 50],
            "당해누계": [750, 2800, 450],
            "집행계": [850, 3200, 500],
            "예산잔액": [400, 4000, 400],
        }
    )


@pytest.fixture
def budget_profile(budget_df: pd.DataFrame) -> dict:
    return profile_dataframe(budget_df)


@pytest.fixture
def budget_excel(tmp_path, budget_df: pd.DataFrame) -> str:
    path = tmp_path / "budget.xlsx"
    budget_df.to_excel(path, index=False)
    return str(path)


# --- profiler / resolver ---


def test_resolve_column_synonym_danghae(budget_df, budget_profile):
    assert resolve_column("당해예산", budget_df, budget_profile) == "당년도예산"


def test_profile_detects_column_roles(budget_profile):
    assert "당년도예산" in budget_profile["likely_amount_columns"]
    assert "비목분류" in budget_profile["likely_category_columns"]
    assert "비용명" in budget_profile["likely_name_columns"]


def test_suggest_columns_on_failure(budget_df, budget_profile):
    suggestions = suggest_columns("당해예산", budget_df, budget_profile)
    assert "당년도예산" in suggestions


# --- router ---


def test_route_top_n_danghae(budget_profile):
    intent = route_query("당해예산 중에 가장 높은 값인 행을 찾아줘", budget_profile)
    assert intent["operations"][0]["type"] == "top_n"


def test_route_describe(budget_profile):
    assert route_query("데이터에 대해서 설명", budget_profile)["operations"][0]["type"] == "describe_dataset"


def test_route_help(budget_profile):
    assert route_query("니가 할 수 있는게 뭐야", budget_profile)["operations"][0]["type"] == "help"


def test_route_value_answer(budget_profile):
    intent = route_query("인쇄비가 얼마지", budget_profile)
    assert intent["operations"][0]["type"] == "value_answer"


def test_route_aggregate_bimok(budget_profile):
    intent = route_query("비목분류별 당년도예산 합계", budget_profile)
    assert intent["operations"][0]["type"] == "aggregate"
    assert "비목" in intent["operations"][0]["group_by"][0] or intent["operations"][0]["group_by"][0] == "비목분류"


def test_route_sort_desc(budget_profile):
    intent = route_query("당년도예산 기준으로 큰 순서대로 보여줘", budget_profile)
    assert intent["operations"][0]["type"] == "sort"
    assert intent["operations"][0]["ascending"] is False


def test_route_filter_budget_gt_zero_no_josa(budget_profile):
    intent = route_query("당년도예산 0보다 큰 항목 보여줘", budget_profile)
    assert intent is not None
    assert intent["operations"][0]["type"] == "filter"
    assert intent["operations"][0]["op"] == ">"
    assert intent["operations"][0]["value"] == 0


def test_route_filter_budget_gt_zero_with_prefix(budget_profile):
    intent = route_query("전체 데이터에서 당년도예산 0보다 높은거 보여줘", budget_profile)
    assert intent is not None
    assert intent["operations"][0]["type"] == "filter"
    assert intent["operations"][0]["op"] == ">"
    assert intent["operations"][0]["value"] == 0


def test_route_show_all_budget_items_not_lookup(budget_profile):
    intent = route_query("당년도 예산 항목 다 보여줘", budget_profile)
    assert intent is not None
    assert intent["operations"][0]["type"] in {"exclude_summary", "filter_row_type"}
    assert not any(op.get("type") == "lookup" for op in intent["operations"])


def test_route_top_n_jeil_high(budget_profile):
    intent = route_query("올해 예산 제일 높은거", budget_profile)
    assert intent is not None
    assert intent["operations"][0]["type"] == "top_n"


def test_validate_blocks_empty_group_by():
    intent = {
        "answer_type": "dataframe",
        "operations": [{"type": "aggregate", "group_by": [], "agg_column": "매출", "agg_func": "sum"}],
        "message": "",
    }
    with pytest.raises(IntentParseError, match="group_by"):
        _validate_intent(intent, {"column_names": ["부서", "매출"]})


# --- operations ---


def test_top_n_returns_server_row(budget_df, budget_profile):
    result = apply_operation(
        budget_df,
        {"type": "top_n", "column": "당해예산", "n": 1, "ascending": False},
        profile=budget_profile,
    )
    assert result["df"]["비용명"].iloc[0] == "서버구입비"
    assert result["df"]["당년도예산"].iloc[0] == 7000


def test_value_answer_printing_cost(budget_df, budget_profile):
    result = apply_operation(
        budget_df, {"type": "value_answer", "row_query": "인쇄비"}, profile=budget_profile
    )
    assert result.get("value_metadata")
    assert result["value_metadata"]["label"] == "인쇄비"
    assert result["df"] is not None
    assert result["df"]["비용명"].iloc[0] == "인쇄비"
    assert result.get("message") is None


# --- executor e2e (no LLM) ---


@patch("llm.intent.chat")
def test_executor_top_n_danghae(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "당해예산 중에 가장 높은 값인 행을 찾아줘")
    assert result["success"]
    assert result["df"]["비용명"].iloc[0] == "서버구입비"
    assert "당년도예산" in result["message"]
    assert "서버구입비" in result["message"]


@patch("llm.intent.chat")
def test_executor_describe(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "데이터에 대해서 설명")
    assert result["success"]
    assert "3행" in result["message"] or "행" in result["message"]
    assert "당년도예산" in result["message"] or "금액" in result["message"]


@patch("llm.intent.chat")
def test_executor_help(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "니가 할 수 있는게 뭐야")
    assert result["success"]
    assert "얼마" in result["message"] or "질문" in result["message"]


@patch("llm.intent.chat")
def test_executor_value_answer(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "인쇄비가 얼마지")
    assert result["success"]
    assert "인쇄비" in result["message"]
    assert result["df"] is not None


@patch("llm.intent.chat")
def test_executor_aggregate_bimok(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "비목분류별 당년도예산 합계")
    assert result["success"]
    assert "당년도예산_sum" in result["df"].columns
    assert len(result["df"]) == 3


@patch("llm.intent.chat")
def test_executor_sort_desc(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "당년도예산 기준으로 큰 순서대로 보여줘")
    assert result["success"]
    assert result["df"]["당년도예산"].iloc[0] == 7000


@patch("llm.intent.chat")
def test_executor_filter_positive(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "당년도집행이 0보다 큰 항목만 보여줘")
    assert result["success"]
    assert len(result["df"]) == 3


@patch("llm.intent.chat")
def test_executor_top_n_remaining_budget(mock_chat, budget_excel):
    mock_chat.side_effect = AssertionError("router should handle this")
    result = run(budget_excel, "예산잔액이 가장 많이 남은 항목 보여줘")
    assert result["success"]
    assert result["df"]["비용명"].iloc[0] == "서버구입비"


@patch("llm.intent.chat")
def test_executor_missing_column_clarify(mock_chat, budget_excel, budget_df, budget_profile):
    mock_chat.side_effect = AssertionError("should not reach LLM")
    result = run(budget_excel, "존재하지않는컬럼xyz 기준으로 큰 순서대로")
    assert result["success"] is False
    assert "찾" in result["error"]




def test_filter_op_not_equal_angle_brackets(budget_df):
    from core.operations import filter_rows

    budget_df = budget_df.copy()
    budget_df["부서"] = ["영업", "개발", "영업"]
    result = filter_rows(budget_df, "부서", "<>", "개발")
    assert len(result) == 2


def test_exclude_summary_rows(budget_df, budget_profile):
    from core.operations import exclude_summary_rows

    df = budget_df.copy()
    df.loc[len(df)] = {
        "비목분류": "합계",
        "비용명": "합계",
        "계획예산": 6800,
        "실행예산": 6280,
        "전년도집행": 5200,
        "당년도예산": 9100,
        "당년도집행": 4300,
        "가집행금액": 350,
        "당해누계": 4000,
        "집행계": 4650,
        "예산잔액": 4800,
    }
    filtered = exclude_summary_rows(df, budget_profile)
    assert len(filtered) == 3
    assert "합계" not in filtered["비용명"].astype(str).tolist()


@patch("llm.intent.chat")
def test_executor_excludes_summary_for_top_n(mock_chat, budget_excel, budget_df, budget_profile, tmp_path):
    mock_chat.side_effect = AssertionError("router should handle this")
    path = tmp_path / "with_total.xlsx"
    df = budget_df.copy()
    df.loc[len(df)] = {
        "비목분류": "합계",
        "비용명": "합계",
        "계획예산": 99999,
        "실행예산": 99999,
        "전년도집행": 99999,
        "당년도예산": 99999,
        "당년도집행": 99999,
        "가집행금액": 99999,
        "당해누계": 99999,
        "집행계": 99999,
        "예산잔액": 99999,
    }
    df.to_excel(path, index=False)

    result = run(str(path), "당해예산 중에 가장 높은 값인 행을 찾아줘")
    assert result["success"]
    assert result["df"]["비용명"].iloc[0] == "서버구입비"
    assert "합계" not in str(result["df"]["비용명"].iloc[0])


def test_generate_response_top_n(budget_df, budget_profile):
    from agent.response_formatter import format_user_response

    execution = {
        "df": budget_df.nlargest(1, "당년도예산"),
        "debug_logs": [],
        "resolved_columns": {"당해예산": "당년도예산"},
        "value_metadata": {},
    }
    intent = {"operations": [{"type": "top_n", "column": "당해예산", "ascending": False}]}
    msg, _, _ = format_user_response("당해예산 최대", intent, execution, budget_profile)
    assert "당년도예산" in msg
    assert "서버구입비" in msg
    assert "행구분" not in msg
