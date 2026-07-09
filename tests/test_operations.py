"""Tests for core.operations — uses synthetic DataFrame fixtures."""

import pandas as pd
import pytest

from core.operations import aggregate, filter_rows, select_columns, sort_rows


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Synthetic sales DataFrame with 이름/부서/매출/연도 columns."""
    return pd.DataFrame(
        {
            "이름": ["김철수", "이영희", "박민수", "최지연", "김철수"],
            "부서": ["영업", "개발", "영업", "개발", "마케팅"],
            "매출": [1000, 2500, 800, 3200, 1500],
            "연도": [2023, 2023, 2024, 2024, 2023],
        }
    )


def _assert_unchanged(original: pd.DataFrame, current: pd.DataFrame) -> None:
    """Verify the original DataFrame was not mutated."""
    pd.testing.assert_frame_equal(original, current)


# --- filter_rows ---


def test_filter_rows_greater_than(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = filter_rows(sample_df, "매출", ">", 1500)
    assert len(result) == 2
    assert all(result["매출"] > 1500)
    _assert_unchanged(original, sample_df)


def test_filter_rows_equals(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = filter_rows(sample_df, "부서", "==", "영업")
    assert len(result) == 2
    assert all(result["부서"] == "영업")
    _assert_unchanged(original, sample_df)


def test_filter_rows_contains(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = filter_rows(sample_df, "이름", "contains", "김")
    assert len(result) == 2
    _assert_unchanged(original, sample_df)


def test_filter_rows_less_than_or_equal(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = filter_rows(sample_df, "매출", "<=", 1000)
    assert len(result) == 2
    _assert_unchanged(original, sample_df)


def test_filter_rows_not_equal(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = filter_rows(sample_df, "부서", "!=", "개발")
    assert len(result) == 3
    _assert_unchanged(original, sample_df)


def test_filter_rows_string_numeric_value(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = filter_rows(sample_df, "매출", ">", "1500")
    assert len(result) == 2
    assert all(result["매출"] > 1500)
    _assert_unchanged(original, sample_df)


def test_filter_rows_string_zero(sample_df: pd.DataFrame) -> None:
    result = filter_rows(sample_df, "매출", ">", "0")
    assert len(result) == 5


def test_filter_rows_currency_string(sample_df: pd.DataFrame) -> None:
    result = filter_rows(sample_df, "매출", ">=", "1,000,000원")
    assert len(result) == 0
    result2 = filter_rows(sample_df, "매출", ">=", "1,000원")
    assert len(result2) == 4


def test_filter_rows_non_numeric_string_raises(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="숫자로 해석할 수 없습니다"):
        filter_rows(sample_df, "매출", ">", "abc")


def test_filter_rows_ordered_compare_on_text_raises(sample_df: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="문자열 컬럼"):
        filter_rows(sample_df, "부서", ">", "영업")


def test_derive_right_numeric_string(sample_df: pd.DataFrame) -> None:
    from core.operations import derive_column

    result = derive_column(sample_df, "조정", "매출", "subtract", "100")
    assert result["조정"].tolist() == [900, 2400, 700, 3100, 1400]


def test_filter_rows_contains_special_chars(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    df = sample_df.copy()
    df["비고"] = ["A+B", "C*D", "E.F", "G(H)", "A+B"]
    result = filter_rows(df, "비고", "contains", "A+B")
    assert len(result) == 2
    _assert_unchanged(original, sample_df)


def test_sort_rows_missing_column(sample_df: pd.DataFrame) -> None:
    with pytest.raises(KeyError, match="매출액"):
        sort_rows(sample_df, "매출액")


def test_select_columns_missing_column(sample_df: pd.DataFrame) -> None:
    with pytest.raises(KeyError):
        select_columns(sample_df, ["이름", "없는컬럼"])


def test_aggregate_missing_column(sample_df: pd.DataFrame) -> None:
    with pytest.raises(KeyError, match="매출액"):
        aggregate(sample_df, ["부서"], "매출액", "sum")


# --- sort_rows ---


def test_sort_rows_ascending(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = sort_rows(sample_df, "매출", ascending=True)
    assert result["매출"].tolist() == sorted(sample_df["매출"].tolist())
    _assert_unchanged(original, sample_df)


def test_sort_rows_descending(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = sort_rows(sample_df, "매출", ascending=False)
    assert result["매출"].tolist() == sorted(sample_df["매출"].tolist(), reverse=True)
    _assert_unchanged(original, sample_df)


# --- select_columns ---


def test_select_columns(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = select_columns(sample_df, ["이름", "매출"])
    assert list(result.columns) == ["이름", "매출"]
    assert len(result) == len(sample_df)
    _assert_unchanged(original, sample_df)


# --- aggregate ---


def test_aggregate_sum(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = aggregate(sample_df, ["부서"], "매출", "sum")
    assert "매출_sum" in result.columns
    sales_by_dept = sample_df.groupby("부서")["매출"].sum()
    for _, row in result.iterrows():
        assert row["매출_sum"] == sales_by_dept[row["부서"]]
    _assert_unchanged(original, sample_df)


def test_aggregate_mean(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = aggregate(sample_df, ["연도"], "매출", "mean")
    assert "매출_mean" in result.columns
    assert len(result) == sample_df["연도"].nunique()
    _assert_unchanged(original, sample_df)


def test_aggregate_count(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = aggregate(sample_df, ["부서"], "매출", "count")
    assert "매출_count" in result.columns
    _assert_unchanged(original, sample_df)


def test_aggregate_max(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = aggregate(sample_df, ["부서"], "매출", "max")
    assert result.loc[result["부서"] == "개발", "매출_max"].iloc[0] == 3200
    _assert_unchanged(original, sample_df)


def test_aggregate_min(sample_df: pd.DataFrame) -> None:
    original = sample_df.copy()
    result = aggregate(sample_df, ["부서"], "매출", "min")
    assert result.loc[result["부서"] == "영업", "매출_min"].iloc[0] == 800
    _assert_unchanged(original, sample_df)
