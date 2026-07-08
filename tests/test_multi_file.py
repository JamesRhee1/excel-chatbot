"""Tests for multi-file Excel analysis."""

from __future__ import annotations

import pandas as pd
import pytest

from agent.multi_executor import run_multi
from agent.multi_router import route_multi_query
from core.derived_metrics import add_budget_metrics
from core.dataset_builder import build_combined_dataset
from core.multi_operations import (
    build_multi_file_summary,
    compare_item_across_files,
    summarize_by_file,
    top_n_by_file,
    top_n_overall,
)
from core.profiler import profile_dataframe
from core.budget_table_normalizer import normalize_budget_sheet
from tests.test_budget_normalizer import _raw_budget_fixture


def _make_file_result(file_name: str, df: pd.DataFrame, *, success: bool = True, error: str | None = None) -> dict:
    if not success:
        return {
            "file_name": file_name,
            "sheet_name": "0",
            "success": False,
            "raw_df": None,
            "normalized_df": None,
            "profile": None,
            "error": error or "load failed",
        }
    return {
        "file_name": file_name,
        "sheet_name": "Sheet1",
        "success": True,
        "raw_df": df,
        "normalized_df": df,
        "profile": profile_dataframe(df),
        "error": None,
    }


def _budget_df(budget_amount: int, item_name: str = "인쇄비", balance: int = 0) -> pd.DataFrame:
    raw = _raw_budget_fixture()
    df = normalize_budget_sheet(raw)
    detail = df[df["행구분"] == "상세"].copy()
    detail.loc[detail["비용명"] == "인쇄비", "당년도예산"] = budget_amount
    detail.loc[detail["비용명"] == "인쇄비", "예산잔액_당해잔액"] = balance
    detail.loc[detail["비용명"] == "인쇄비", "예산잔액_합계"] = balance
    if item_name != "인쇄비":
        detail.loc[detail["비용명"] == "회의비", "비용명"] = item_name
    # keep subtotal/total rows for realism
    other = df[df["행구분"] != "상세"]
    return pd.concat([detail, other], ignore_index=True)


@pytest.fixture
def two_file_results() -> list[dict]:
    df_a = _budget_df(4_000_000, balance=2_000_000)
    df_b = _budget_df(3_000_000, balance=0)
    return [
        _make_file_result("4예실대비표.xlsx", df_a),
        _make_file_result("5예실대비표.xlsx", df_b),
    ]


@pytest.fixture
def combined_df(two_file_results):
    df = build_combined_dataset(two_file_results)
    return add_budget_metrics(df)


@pytest.fixture
def normalized_budget_profile(combined_df):
    return profile_dataframe(combined_df, domain="budget_comparison")


# --- dataset_builder ---


def test_build_combined_dataset_adds_source_file(two_file_results):
    combined = build_combined_dataset(two_file_results)
    assert "source_file" in combined.columns
    assert "source_sheet" in combined.columns
    expected_rows = sum(len(r["normalized_df"]) for r in two_file_results if r["success"])
    assert len(combined) == expected_rows
    assert set(combined["source_file"]) == {"4예실대비표.xlsx", "5예실대비표.xlsx"}


def test_build_combined_dataset_skips_failed_files(two_file_results):
    results = two_file_results + [
        _make_file_result("bad.xlsx", pd.DataFrame(), success=False, error="corrupt"),
    ]
    combined = build_combined_dataset(results)
    assert "bad.xlsx" not in combined["source_file"].unique()
    assert combined["source_file"].nunique() == 2


def test_build_combined_dataset_raises_when_all_failed():
    results = [_make_file_result("a.xlsx", pd.DataFrame(), success=False)]
    with pytest.raises(ValueError, match="통합할 수 있는"):
        build_combined_dataset(results)


# --- derived_metrics ---


def test_add_budget_metrics(combined_df, normalized_budget_profile):
    from domains.budget_comparison import add_budget_metrics

    result = add_budget_metrics(combined_df)
    assert "집행률" in result.columns
    assert "잔액률" in result.columns
    assert "예산대비집행차이" in result.columns
    # zero budget should not raise
    zero_row = result[result["당년도예산"] == 0]
    if not zero_row.empty:
        assert pd.notna(zero_row["집행률"].iloc[0]) or zero_row["집행률"].iloc[0] == 0


# --- multi_operations ---


def test_summarize_by_file_budget_sum(combined_df):
    result = summarize_by_file(combined_df, "당년도예산", row_type="상세")
    assert "source_file" in result.columns
    assert "당년도예산_sum" in result.columns
    assert len(result) == 2


def test_compare_item_across_files_printing(combined_df, normalized_budget_profile):
    result = compare_item_across_files(combined_df, "인쇄비", profile=normalized_budget_profile)
    assert not result.empty
    assert "source_file" in result.columns
    assert "비용명" in result.columns
    assert "당년도예산" in result.columns
    assert result["source_file"].nunique() == 2


def test_top_n_by_file(combined_df):
    result = top_n_by_file(combined_df, "당년도예산", n=1, ascending=False, row_type="상세")
    assert len(result) == 2
    assert "source_file" in result.columns
    assert result.groupby("source_file").size().max() == 1


def test_top_n_overall(combined_df):
    result = top_n_overall(combined_df, "예산잔액_합계", n=3, ascending=False, row_type="상세")
    assert len(result) <= 3
    assert "source_file" in result.columns


def test_build_multi_file_summary(combined_df, normalized_budget_profile):
    summary = build_multi_file_summary(combined_df, profile=normalized_budget_profile)
    assert summary["file_count"] == 2
    assert summary["total_rows"] == len(combined_df)
    assert "budget_sum_by_file" in summary


# --- multi_router ---


def test_route_multi_query_combine():
    intent = route_multi_query("이 파일들 통합해줘")
    assert intent is not None
    assert intent["operations"][0]["type"] == "combine_dataset"


def test_route_multi_query_compare_item():
    intent = route_multi_query("인쇄비를 파일별로 비교해줘")
    assert intent is not None
    assert intent["operations"][0]["type"] == "compare_item_across_files"
    assert intent["operations"][0]["item_query"] == "인쇄비"


def test_route_multi_query_summarize(normalized_budget_profile):
    intent = route_multi_query("파일별 당년도예산 합계 비교해줘", normalized_budget_profile)
    assert intent is not None
    assert intent["operations"][0]["type"] == "summarize_by_file"


def test_route_multi_query_top_n_by_file(normalized_budget_profile):
    intent = route_multi_query("각 파일에서 당년도예산이 가장 높은 항목 알려줘", normalized_budget_profile)
    assert intent is not None
    assert intent["operations"][0]["type"] == "top_n_by_file"


def test_route_multi_query_top_n_overall(normalized_budget_profile):
    intent = route_multi_query("전체 파일에서 예산잔액이 가장 큰 항목 5개 보여줘", normalized_budget_profile)
    assert intent is not None
    assert intent["operations"][0]["type"] == "top_n_overall"
    assert intent["operations"][0]["n"] == 5


# --- multi_executor ---


def test_run_multi_combine_dataset(two_file_results):
    result = run_multi(two_file_results, "통합자료 만들어줘")
    assert result["success"]
    assert result["combined_df"] is not None
    assert len(result["combined_df"]) > 0
    assert "통합" in result["message"]


def test_run_multi_compare_printing(two_file_results):
    result = run_multi(two_file_results, "인쇄비를 파일별로 비교해줘")
    assert result["success"]
    assert "인쇄비" in result["message"]
    assert "4예실대비표.xlsx" in result["message"]
    assert "행구분" not in result["message"]
