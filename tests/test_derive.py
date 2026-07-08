"""Tests for derive column operation."""

from __future__ import annotations

import pandas as pd
import pytest

from agent.router import route_query
from agent.tools import apply_operation
from core.operations import derive_column
from core.profiler import profile_dataframe


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "예산잔액": [1000, 2000],
            "가집행금액": [200, 500],
            "당년도예산": [0, 3000],
        }
    )


@pytest.fixture
def sample_profile(sample_df: pd.DataFrame) -> dict:
    return profile_dataframe(sample_df, domain="generic")


def test_derive_subtract(sample_df: pd.DataFrame) -> None:
    result = derive_column(sample_df, "차이", "예산잔액", "subtract", "가집행금액")
    assert result["차이"].tolist() == [800, 1500]
    assert sample_df.columns.tolist() == ["예산잔액", "가집행금액", "당년도예산"]


def test_derive_percent(sample_df: pd.DataFrame) -> None:
    result = derive_column(sample_df, "비율", "가집행금액", "percent", "예산잔액")
    assert result["비율"].iloc[0] == pytest.approx(20.0)
    assert result["비율"].iloc[1] == pytest.approx(25.0)


def test_derive_divide_by_zero_is_nan(sample_df: pd.DataFrame) -> None:
    result = derive_column(sample_df, "비율", "예산잔액", "divide", "당년도예산")
    assert pd.isna(result["비율"].iloc[0])
    assert result["비율"].iloc[1] == pytest.approx(2000 / 3000)


def test_apply_derive_resolves_columns(sample_df: pd.DataFrame, sample_profile: dict) -> None:
    outcome = apply_operation(
        sample_df,
        {
            "type": "derive",
            "new_column": "잔액차",
            "left": "예산잔액",
            "op": "subtract",
            "right": "가집행금액",
        },
        profile=sample_profile,
    )
    assert "잔액차" in outcome["df"].columns
    assert outcome["df"]["잔액차"].iloc[0] == 800


def test_route_derive_subtract_pattern(sample_profile: dict) -> None:
    intent = route_query("예산잔액에서 가집행금액 뺀 값 컬럼 만들어줘", sample_profile)
    assert intent is not None
    op = intent["operations"][0]
    assert op["type"] == "derive"
    assert op["op"] == "subtract"


def test_route_derive_percent_pattern(sample_profile: dict) -> None:
    intent = route_query("가집행금액 대비 예산잔액 비율", sample_profile)
    assert intent is not None
    assert intent["operations"][0]["op"] == "percent"
