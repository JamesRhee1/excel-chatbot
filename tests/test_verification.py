"""Tests for core.verification invariant checks."""

from __future__ import annotations

import pandas as pd
import pytest

from core.operations import (
    aggregate,
    derive_column,
    exclude_summary_rows,
    filter_rows,
    select_columns,
    sort_rows,
    top_n_rows,
)
from core.verification import verify_operation


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "이름": ["김철수", "이영희", "박민수", "합계"],
            "부서": ["영업", "개발", "영업", "합계"],
            "매출": [1000, 2500, 800, 4300],
        }
    )


def test_filter_passes_on_valid_output(sample_df: pd.DataFrame) -> None:
    output = filter_rows(sample_df, "매출", ">", 900)
    report = verify_operation("filter", sample_df, output, {"column": "매출", "op": ">", "value": 900})
    assert report.passed


def test_filter_fails_when_rows_increase(sample_df: pd.DataFrame) -> None:
    corrupted = pd.concat([sample_df, sample_df.iloc[[0]]], ignore_index=True)
    report = verify_operation("filter", sample_df, corrupted, {})
    assert not report.passed


def test_sort_passes_on_valid_output(sample_df: pd.DataFrame) -> None:
    output = sort_rows(sample_df, "매출", ascending=False)
    report = verify_operation("sort", sample_df, output, {"column": "매출", "ascending": False})
    assert report.passed


def test_sort_fails_when_row_added(sample_df: pd.DataFrame) -> None:
    corrupted = pd.concat([sort_rows(sample_df, "매출"), sample_df.iloc[[0]]], ignore_index=True)
    report = verify_operation("sort", sample_df, corrupted, {"column": "매출"})
    assert not report.passed


def test_aggregate_sum_preservation(sample_df: pd.DataFrame) -> None:
    detail = sample_df[sample_df["이름"] != "합계"].copy()
    output = aggregate(detail, ["부서"], "매출", "sum")
    report = verify_operation(
        "aggregate",
        detail,
        output,
        {"group_by": ["부서"], "agg_column": "매출", "agg_func": "sum"},
    )
    assert report.passed


def test_aggregate_fails_on_sum_mismatch(sample_df: pd.DataFrame) -> None:
    detail = sample_df[sample_df["이름"] != "합계"].copy()
    output = aggregate(detail, ["부서"], "매출", "sum")
    output.loc[0, "매출_sum"] += 100
    report = verify_operation(
        "aggregate",
        detail,
        output,
        {"group_by": ["부서"], "agg_column": "매출", "agg_func": "sum"},
    )
    assert not report.passed


def test_top_n_passes(sample_df: pd.DataFrame) -> None:
    output = top_n_rows(sample_df, "매출", n=2, ascending=False)
    report = verify_operation("top_n", sample_df, output, {"column": "매출", "n": 2})
    assert report.passed


def test_top_n_fails_when_extra_row(sample_df: pd.DataFrame) -> None:
    output = top_n_rows(sample_df, "매출", n=2, ascending=False)
    corrupted = pd.concat([output, output.iloc[[0]]], ignore_index=True)
    report = verify_operation("top_n", sample_df, corrupted, {"column": "매출", "n": 2})
    assert not report.passed


def test_derive_passes(sample_df: pd.DataFrame) -> None:
    output = derive_column(sample_df, "매출2", "매출", "multiply", 2)
    report = verify_operation(
        "derive",
        sample_df,
        output,
        {"new_column": "매출2", "left": "매출", "op": "multiply", "right": 2},
    )
    assert report.passed


def test_select_passes(sample_df: pd.DataFrame) -> None:
    output = select_columns(sample_df, ["이름", "매출"])
    report = verify_operation("select", sample_df, output, {"columns": ["이름", "매출"]})
    assert report.passed


def test_exclude_summary_passes(sample_df: pd.DataFrame) -> None:
    profile = {"likely_name_columns": ["이름"], "likely_category_columns": ["부서"]}
    output = exclude_summary_rows(sample_df, profile)
    report = verify_operation(
        "exclude_summary",
        sample_df,
        output,
        {"_profile": profile},
    )
    assert report.passed


def test_unregistered_op_skips_with_notice(sample_df: pd.DataFrame) -> None:
    report = verify_operation("help", sample_df, sample_df, {})
    assert report.passed
    assert "검사를 건너뜁니다" in report.checks[0].detail
