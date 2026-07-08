"""Tests for conversation context chaining via last_result."""

from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
from unittest.mock import patch

from agent.executor import run
from agent.router import route_query
from core.profiler import profile_dataframe
from core.workspace import LAST_RESULT_TABLE, Workspace


def test_route_context_top_n_sets_last_result_source() -> None:
    profile = profile_dataframe(
        pd.DataFrame({"금액": [10, 50, 30], "이름": ["a", "b", "c"]}),
        domain="generic",
    )
    intent = route_query("이 중에서 상위 2개", profile)
    assert intent is not None
    assert intent["operations"][0]["type"] == "top_n"
    assert intent["operations"][0]["source"] == LAST_RESULT_TABLE
    assert intent["operations"][0]["n"] == 2


def test_followup_without_context_uses_original_table() -> None:
    ws = Workspace()
    df = pd.DataFrame(
        {
            "비목분류": ["운영비", "장비비", "회의비", "합계"],
            "비용명": ["인쇄비", "서버", "회의비", "합계"],
            "당년도예산": [1200, 7000, 900, 9100],
        }
    )
    profile = profile_dataframe(df, domain="generic")
    ws.upsert_table("main", df, "budget.xlsx", profile=profile, domain="generic")

    first = run(user_message="당년도예산 가장 높은 행 찾아줘", workspace=ws)
    assert first["success"]
    assert len(first["raw_df"]) == 1

    second = run(user_message="당년도예산 기준으로 큰 순서대로", workspace=ws)
    assert second["success"]
    assert second["raw_df"] is not None
    assert len(second["raw_df"]) == 3


def test_followup_top_n_uses_last_result() -> None:
    ws = Workspace()
    df = pd.DataFrame(
        {
            "비목분류": ["운영비", "장비비", "회의비", "합계"],
            "비용명": ["인쇄비", "서버", "회의비", "합계"],
            "당년도예산": [1200, 7000, 900, 9100],
        }
    )
    profile = profile_dataframe(df, domain="generic")
    ws.upsert_table("main", df, "budget.xlsx", profile=profile, domain="generic")

    first = run(user_message="당년도예산 기준으로 큰 순서대로", workspace=ws)
    assert first["success"]
    assert ws.get(LAST_RESULT_TABLE) is not None

    second = run(user_message="이 중에서 상위 2개", workspace=ws)
    assert second["success"]
    assert second["raw_df"] is not None
    assert len(second["raw_df"]) == 2
    assert second["raw_df"]["당년도예산"].iloc[0] == 7000


def test_context_top_n_prefers_last_ranked_column_over_profile_default() -> None:
    ws = Workspace()
    df = pd.DataFrame(
        {
            "항목": ["a", "b", "c", "d"],
            "금액A": [100, 500, 200, 700],
            "금액B": [5, 1, 9, 3],
        }
    )
    profile = profile_dataframe(df, domain="generic")
    ws.upsert_table("main", df, "rank.xlsx", profile=profile, domain="generic")

    first = run(user_message="금액B 기준으로 큰 순서대로", workspace=ws)
    assert first["success"]
    assert ws.get_state("last_ranked_column") == "금액B"

    second = run(user_message="이 중에서 상위 2개", workspace=ws)
    assert second["success"]
    assert second["operations"][-1]["column"] == "금액B"
    assert second["raw_df"]["금액B"].tolist() == [9, 5]
    assert "정렬 기준: 금액B (자동 선택)" in second["message"]


def test_context_top_n_avoids_code_like_column_auto_selection() -> None:
    ws = Workspace()
    df = pd.DataFrame(
        {
            "비목코드": [1001, 1002, 1003, 1004],
            "당년도예산": [200, 900, 400, 700],
            "항목명": ["a", "b", "c", "d"],
        }
    )
    profile = profile_dataframe(df, domain="generic")
    ws.upsert_table("main", df, "budget.xlsx", profile=profile, domain="generic")
    ws.upsert_table(LAST_RESULT_TABLE, df, "previous_turn", profile=profile, domain="generic")

    result = run(user_message="이 중에서 상위 3개", workspace=ws)
    assert result["success"]
    assert result["operations"][-1]["column"] == "당년도예산"
    assert "비목코드" not in (result["operations"][-1]["column"],)
    assert "정렬 기준: 당년도예산 (자동 선택)" in result["message"]


def test_context_top_n_without_numeric_column_returns_clarify_error() -> None:
    ws = Workspace()
    df = pd.DataFrame({"이름": ["a", "b"], "부서": ["영업", "개발"]})
    profile = profile_dataframe(df, domain="generic")
    ws.upsert_table("main", df, "text.xlsx", profile=profile, domain="generic")
    ws.upsert_table(LAST_RESULT_TABLE, df, "previous_turn", profile=profile, domain="generic")

    intent = {"answer_type": "dataframe", "operations": [{"type": "top_n", "n": 2, "ascending": False}]}
    with patch("agent.executor.route_query", return_value=intent):
        result = run(user_message="이 중에서 상위 2개", workspace=ws)
    assert result["success"] is False
    assert "정렬 기준 컬럼을 자동으로 선택할 수 없습니다" in (result["error"] or "")


def test_llm_profile_uses_current_source_table_after_derive(tmp_path: Path, monkeypatch) -> None:
    trace_dir = tmp_path / "traces"
    monkeypatch.setenv("EXCEL_CHATBOT_TRACE_DIR", str(trace_dir))
    from agent import executor as executor_module

    original_writer = executor_module._TRACE_WRITER
    executor_module._TRACE_WRITER = executor_module.TraceWriter(trace_dir=trace_dir)

    ws = Workspace()
    df = pd.DataFrame(
        {
            "매출": [100, 300, 200],
            "비용": [50, 120, 100],
            "항목": ["a", "b", "c"],
        }
    )
    profile = profile_dataframe(df, domain="generic")
    ws.upsert_table("main", df, "sales.xlsx", profile=profile, domain="generic")

    first_intent = {
        "answer_type": "dataframe",
        "operations": [
            {"type": "derive", "new_column": "수익률", "left": "매출", "op": "divide", "right": "비용", "save_as": "calc"}
        ],
    }

    def _parse_with_current_profile(user_message: str, profile_arg: dict, model=None):  # noqa: ARG001
        assert "수익률" in profile_arg.get("numeric_columns", [])
        assert "수익률" in profile_arg.get("sample_values_by_column", {})
        return {
            "answer_type": "dataframe",
            "operations": [{"type": "sort", "column": "수익률", "ascending": False, "source": LAST_RESULT_TABLE}],
            "message": "",
        }

    try:
        with (
            patch("agent.executor.route_query", side_effect=[first_intent, None]),
            patch("agent.executor.parse_intent", side_effect=_parse_with_current_profile),
        ):
            first = run(user_message="매출 대비 비용 비율 컬럼 만들어줘", workspace=ws)
            assert first["success"]
            second = run(user_message="이 중에서 수익률 기준으로 정렬해줘", workspace=ws)
    finally:
        executor_module._TRACE_WRITER = original_writer

    assert second["success"]
    assert second["operations"][-1]["column"] == "수익률"
    assert second["raw_df"] is not None
    assert second["raw_df"]["수익률"].iloc[0] == max(second["raw_df"]["수익률"])

    trace_files = sorted(trace_dir.glob("traces_*.jsonl"))
    assert trace_files
    payload = json.loads(trace_files[-1].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["intent"]["operations"][-1]["column"] == "수익률"
