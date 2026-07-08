"""Tests for conversation context chaining via last_result."""

from __future__ import annotations

import pandas as pd

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
