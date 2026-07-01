"""Pure DataFrame operations — inputs are never mutated."""

from __future__ import annotations

import pandas as pd

_VALID_OPS = {">", "<", ">=", "<=", "==", "!=", "contains"}
_VALID_AGG_FUNCS = {"sum", "mean", "count", "max", "min"}


def filter_rows(
    df: pd.DataFrame,
    column: str,
    op: str,
    value,
) -> pd.DataFrame:
    """Filter rows by a column condition.

    Args:
        df: Input DataFrame.
        column: Column name to filter on.
        op: Comparison operator ('>', '<', '>=', '<=', '==', '!=', 'contains').
        value: Value to compare against.

    Returns:
        Filtered copy of the DataFrame.
    """
    if op not in _VALID_OPS:
        raise ValueError(f"Unsupported operator: {op!r}. Must be one of {_VALID_OPS}")

    series = df[column]
    if op == ">":
        mask = series > value
    elif op == "<":
        mask = series < value
    elif op == ">=":
        mask = series >= value
    elif op == "<=":
        mask = series <= value
    elif op == "==":
        mask = series == value
    elif op == "!=":
        mask = series != value
    else:  # contains
        mask = series.astype(str).str.contains(str(value), na=False)

    return df.loc[mask].copy()


def sort_rows(
    df: pd.DataFrame,
    column: str,
    ascending: bool = True,
) -> pd.DataFrame:
    """Sort rows by a column.

    Args:
        df: Input DataFrame.
        column: Column name to sort by.
        ascending: Sort direction (default: ascending).

    Returns:
        Sorted copy of the DataFrame.
    """
    return df.sort_values(by=column, ascending=ascending).reset_index(drop=True)


def select_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Select a subset of columns.

    Args:
        df: Input DataFrame.
        columns: List of column names to keep.

    Returns:
        DataFrame containing only the selected columns.
    """
    return df[columns].copy()


def aggregate(
    df: pd.DataFrame,
    group_by: list[str],
    agg_column: str,
    agg_func: str,
) -> pd.DataFrame:
    """Group rows and apply an aggregation function.

    Args:
        df: Input DataFrame.
        group_by: Columns to group by.
        agg_column: Column to aggregate.
        agg_func: Aggregation function ('sum', 'mean', 'count', 'max', 'min').

    Returns:
        Aggregated DataFrame.
    """
    if agg_func not in _VALID_AGG_FUNCS:
        raise ValueError(
            f"Unsupported agg_func: {agg_func!r}. Must be one of {_VALID_AGG_FUNCS}"
        )

    grouped = df.groupby(group_by, as_index=False)[agg_column]
    result = grouped.agg(agg_func)
    result = result.rename(columns={agg_column: f"{agg_column}_{agg_func}"})
    return result
