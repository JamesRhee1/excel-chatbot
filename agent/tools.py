"""Dispatch table mapping intent operation types to core functions."""

from __future__ import annotations

from typing import Callable

import pandas as pd

from core.operations import aggregate, filter_rows, select_columns, sort_rows

OperationHandler = Callable[[pd.DataFrame, dict], pd.DataFrame]

_SUPPORTED_TYPES = frozenset({"filter", "sort", "select", "aggregate"})


def _apply_filter(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    return filter_rows(df, op["column"], op["op"], op["value"])


def _apply_sort(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    return sort_rows(df, op["column"], op.get("ascending", True))


def _apply_select(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    return select_columns(df, op["columns"])


def _apply_aggregate(df: pd.DataFrame, op: dict) -> pd.DataFrame:
    return aggregate(df, op["group_by"], op["agg_column"], op["agg_func"])


_DISPATCH: dict[str, OperationHandler] = {
    "filter": _apply_filter,
    "sort": _apply_sort,
    "select": _apply_select,
    "aggregate": _apply_aggregate,
}


def apply_operation(df: pd.DataFrame, operation: dict) -> pd.DataFrame:
    """Apply a single structured operation to a DataFrame.

    Args:
        df: Input DataFrame.
        operation: Operation dict with a "type" key and type-specific fields.

    Returns:
        Transformed copy of the DataFrame.

    Raises:
        ValueError: If the operation type is not supported.
    """
    op_type = operation.get("type")
    if op_type not in _SUPPORTED_TYPES:
        supported = ", ".join(sorted(_SUPPORTED_TYPES))
        raise ValueError(
            f"지원하지 않는 operation type: {op_type!r}. "
            f"지원 타입: {supported}"
        )

    return _DISPATCH[op_type](df, operation)
