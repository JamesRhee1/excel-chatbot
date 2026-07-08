"""Dispatch table mapping intent operation types to core functions."""

from __future__ import annotations

from typing import Callable, TypedDict

import pandas as pd

from agent.op_registry import SUPPORTED_OPERATION_TYPES, validate_operation
from core.column_resolver import resolve_column, resolve_columns
from core.operations import (
    aggregate,
    exclude_summary_rows,
    filter_row_types,
    filter_rows,
    lookup_rows,
    normalize_filter_op,
    select_columns,
    sort_rows,
    summary_stats,
    top_n_rows,
    value_answer,
)

_SUPPORTED_TYPES = SUPPORTED_OPERATION_TYPES


class ApplyResult(TypedDict, total=False):
    df: pd.DataFrame | None
    message: str | None
    debug_log: str | None
    resolved_columns: dict[str, str]
    value_metadata: dict
    stats: dict


OperationHandler = Callable[[pd.DataFrame, dict, dict], ApplyResult]


def _result_df(df: pd.DataFrame, resolved: dict | None = None, message: str | None = None) -> ApplyResult:
    result: ApplyResult = {"df": df, "message": message, "resolved_columns": resolved or {}}
    return result


def _result_message(
    message: str,
    df: pd.DataFrame | None = None,
    resolved: dict | None = None,
    **extra,
) -> ApplyResult:
    result: ApplyResult = {"df": df, "message": message, "resolved_columns": resolved or {}}
    result.update(extra)
    return result


def _track_resolution(resolved: dict, user_expr: str, actual: str) -> None:
    if user_expr != actual:
        resolved[user_expr] = actual


def _apply_filter(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    resolved: dict[str, str] = {}
    user_col = op["column"]
    column = resolve_column(user_col, df, profile)
    _track_resolution(resolved, user_col, column)
    filter_op = normalize_filter_op(op["op"])
    return _result_df(filter_rows(df, column, filter_op, op["value"]), resolved)


def _apply_exclude_summary(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    filtered = exclude_summary_rows(df, profile)
    removed = len(df) - len(filtered)
    debug_log = None
    if removed > 0:
        if profile.get("is_budget_table"):
            debug_log = f"상세 항목 {len(filtered)}개만 분석 대상으로 선정했습니다."
        else:
            debug_log = f"합계/소계/총계로 보이는 {removed}개 행을 제외하고 분석했습니다."
    return _result_df(filtered, message=None) | {"debug_log": debug_log}


def _apply_filter_row_type(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    row_types = op.get("row_types") or ["상세"]
    filtered = filter_row_types(df, row_types)
    label = ", ".join(row_types)
    debug_log = f"행구분이 '{label}'인 {len(filtered)}개 행을 분석 대상으로 선정했습니다."
    return _result_df(filtered, message=None) | {"debug_log": debug_log}


def _apply_sort(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    resolved: dict[str, str] = {}
    user_col = op["column"]
    column = resolve_column(user_col, df, profile)
    _track_resolution(resolved, user_col, column)
    return _result_df(sort_rows(df, column, op.get("ascending", True)), resolved)


def _apply_select(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    resolved: dict[str, str] = {}
    columns = []
    for col in op["columns"]:
        actual = resolve_column(col, df, profile)
        _track_resolution(resolved, col, actual)
        columns.append(actual)
    return _result_df(select_columns(df, columns), resolved)


def _apply_aggregate(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    resolved: dict[str, str] = {}
    group_by = []
    for col in op["group_by"]:
        actual = resolve_column(col, df, profile)
        _track_resolution(resolved, col, actual)
        group_by.append(actual)
    user_agg = op["agg_column"]
    agg_column = resolve_column(user_agg, df, profile)
    _track_resolution(resolved, user_agg, agg_column)
    return _result_df(aggregate(df, group_by, agg_column, op["agg_func"]), resolved)


def _apply_top_n(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    resolved: dict[str, str] = {}
    user_col = op["column"]
    column = resolve_column(user_col, df, profile)
    _track_resolution(resolved, user_col, column)
    return _result_df(
        top_n_rows(df, column, n=op.get("n", 1), ascending=op.get("ascending", False)),
        resolved,
    )


def _apply_lookup(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    columns = op.get("columns")
    if columns:
        columns = resolve_columns(columns, df, profile)
    return _result_df(lookup_rows(df, op["query"], columns=columns))


def _apply_describe_dataset(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    return _result_df(df if not df.empty else None)


def _apply_value_answer(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    value_columns = op.get("value_columns")
    if value_columns:
        value_columns = resolve_columns(value_columns, df, profile)
    result_df, metadata = value_answer(
        df, op["row_query"], value_columns=value_columns, profile=profile,
    )
    return ApplyResult(
        df=result_df if not result_df.empty else None,
        value_metadata=metadata,
    )


def _apply_help(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    return ApplyResult(df=None)


def _apply_summary_stats(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    resolved: dict[str, str] = {}
    user_col = op["column"]
    column = resolve_column(user_col, df, profile)
    _track_resolution(resolved, user_col, column)
    stats = summary_stats(df, column)
    return ApplyResult(df=None, resolved_columns=resolved, stats=stats)


def _apply_clarify(df: pd.DataFrame, op: dict, profile: dict) -> ApplyResult:
    from llm.intent import UNKNOWN_MESSAGE

    return ApplyResult(message=op.get("message") or UNKNOWN_MESSAGE)


_DISPATCH: dict[str, OperationHandler] = {
    "filter": _apply_filter,
    "sort": _apply_sort,
    "select": _apply_select,
    "aggregate": _apply_aggregate,
    "top_n": _apply_top_n,
    "lookup": _apply_lookup,
    "describe_dataset": _apply_describe_dataset,
    "value_answer": _apply_value_answer,
    "help": _apply_help,
    "summary_stats": _apply_summary_stats,
    "clarify": _apply_clarify,
    "exclude_summary": _apply_exclude_summary,
    "filter_row_type": _apply_filter_row_type,
}


def apply_operation(
    df: pd.DataFrame,
    operation: dict,
    profile: dict | None = None,
) -> ApplyResult:
    op_type = operation.get("type")
    if op_type not in _SUPPORTED_TYPES:
        supported = ", ".join(sorted(_SUPPORTED_TYPES))
        raise ValueError(
            f"지원하지 않는 operation type: {op_type!r}. 지원 타입: {supported}"
        )
    validate_operation(operation, 0)
    if profile is None:
        from core.profiler import profile_dataframe
        profile = profile_dataframe(df)
    return _DISPATCH[op_type](df, operation, profile)
