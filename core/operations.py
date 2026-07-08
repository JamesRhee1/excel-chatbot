"""Pure DataFrame operations — inputs are never mutated."""

from __future__ import annotations

import pandas as pd

_VALID_OPS = {">", "<", ">=", "<=", "==", "!=", "<>", "contains"}
_VALID_AGG_FUNCS = {"sum", "mean", "count", "max", "min"}
_SUMMARY_TOKENS = ("합계", "소계", "총계", "합 계", "소 계", "총 계", "total", "subtotal", "grand total")


def normalize_filter_op(op: str) -> str:
    """Normalize filter operator aliases (e.g. SQL-style <> -> !=)."""
    normalized = str(op).strip()
    if normalized == "<>":
        return "!="
    return normalized


def is_summary_text(value) -> bool:
    """Return True if a cell value looks like a total/subtotal row label."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    text = str(value).strip().lower().replace(" ", "")
    if not text:
        return False
    compact_tokens = ("합계", "소계", "총계", "total", "subtotal")
    return any(token in text for token in compact_tokens)


def exclude_summary_rows(df: pd.DataFrame, profile: dict) -> pd.DataFrame:
    """Remove summary/total rows — uses domain row-type config or heuristics."""
    summary_cfg = profile.get("summary_row_config") or {}
    row_type_col = summary_cfg.get("row_type_column")
    detail_type = summary_cfg.get("detail_row_type")
    if row_type_col and detail_type and row_type_col in df.columns:
        return df[df[row_type_col] == detail_type].copy()
    check_cols: list[str] = list(
        dict.fromkeys(
            (profile.get("likely_name_columns") or [])
            + (profile.get("likely_category_columns") or [])
            + [c for c in profile.get("text_columns", []) if not str(c).startswith("Unnamed")]
        )
    )
    if not check_cols:
        check_cols = [c for c in df.columns.astype(str) if not str(c).startswith("Unnamed")]

    mask = pd.Series(True, index=df.index)
    for col in check_cols:
        if col not in df.columns:
            continue
        col_mask = ~df[col].apply(is_summary_text)
        mask &= col_mask
    return df.loc[mask].copy()


def filter_row_types(df: pd.DataFrame, row_types: list[str], profile: dict | None = None) -> pd.DataFrame:
    """Filter rows by configured row-type column when present."""
    profile = profile or {}
    summary_cfg = profile.get("summary_row_config") or {}
    row_type_col = summary_cfg.get("row_type_column")
    if row_type_col and row_type_col in df.columns:
        return df[df[row_type_col].isin(row_types)].copy()

    detail_type = summary_cfg.get("detail_row_type")
    if detail_type and row_types == [detail_type]:
        return exclude_summary_rows(df, profile)
    return df.copy()


def describe_dataset_info(df: pd.DataFrame, profile: dict) -> dict:
    """Return structured dataset summary for response generation."""
    missing = {k: v for k, v in profile.get("missing_counts", {}).items() if v > 0}
    return {
        "rows": profile["rows"],
        "columns": profile["columns"],
        "column_names": profile["column_names"],
        "numeric_columns": profile.get("numeric_columns", []),
        "text_columns": profile.get("text_columns", []),
        "likely_amount_columns": profile.get("likely_amount_columns", []),
        "likely_category_columns": profile.get("likely_category_columns", []),
        "likely_name_columns": profile.get("likely_name_columns", []),
        "unnamed_columns": profile.get("unnamed_columns", []),
        "missing_counts": missing,
    }


def _require_columns(df: pd.DataFrame, columns: list[str]) -> None:
    missing = [col for col in columns if col not in df.columns]
    if not missing:
        return
    if len(missing) == 1:
        raise KeyError(missing[0])
    raise KeyError(missing)


def _coerce_numeric_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _coerce_filter_value(series: pd.Series, value):
    series_num = _coerce_numeric_series(series)
    if pd.api.types.is_numeric_dtype(series_num) and series_num.notna().any():
        if isinstance(value, str):
            stripped = value.strip().replace(",", "")
            try:
                return float(stripped) if "." in stripped else int(stripped)
            except ValueError:
                pass
        return value
    return value


def _format_amount(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    try:
        num = float(val)
        if pd.isna(num):
            return ""
        if num.is_integer():
            return f"{int(num):,}원"
        return f"{num:,.0f}원"
    except (TypeError, ValueError):
        text = str(val).strip()
        return text if text else ""


def filter_rows(df: pd.DataFrame, column: str, op: str, value) -> pd.DataFrame:
    op = normalize_filter_op(op)
    if op not in _VALID_OPS:
        raise ValueError(f"Unsupported operator: {op!r}. Must be one of {_VALID_OPS}")
    _require_columns(df, [column])
    series = df[column]

    if op == "contains":
        mask = series.astype(str).str.contains(str(value), na=False, regex=False)
    elif op in {">", "<", ">=", "<="}:
        numeric = _coerce_numeric_series(series)
        cmp_val = _coerce_filter_value(series, value)
        if op == ">":
            mask = numeric > cmp_val
        elif op == "<":
            mask = numeric < cmp_val
        elif op == ">=":
            mask = numeric >= cmp_val
        else:
            mask = numeric <= cmp_val
    else:
        numeric = _coerce_numeric_series(series)
        if numeric.notna().sum() >= max(1, series.notna().sum() * 0.5):
            cmp_val = _coerce_filter_value(series, value)
            mask = numeric == cmp_val if op == "==" else numeric != cmp_val
        else:
            cmp_val = str(value)
            str_series = series.astype(str)
            mask = str_series == cmp_val if op == "==" else str_series != cmp_val

    return df.loc[mask].copy()


def sort_rows(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
    _require_columns(df, [column])
    working = df.copy()
    working["_sort_key"] = _coerce_numeric_series(working[column])
    if working["_sort_key"].notna().any():
        result = working.sort_values("_sort_key", ascending=ascending, na_position="last")
    else:
        result = working.sort_values(by=column, ascending=ascending, na_position="last")
    return result.drop(columns=["_sort_key"], errors="ignore").reset_index(drop=True)


def select_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    _require_columns(df, columns)
    return df[columns].copy()


def aggregate(
    df: pd.DataFrame, group_by: list[str], agg_column: str, agg_func: str
) -> pd.DataFrame:
    if agg_func not in _VALID_AGG_FUNCS:
        raise ValueError(
            f"Unsupported agg_func: {agg_func!r}. Must be one of {_VALID_AGG_FUNCS}"
        )
    _require_columns(df, list(group_by) + [agg_column])
    grouped = df.groupby(group_by, as_index=False)[agg_column]
    result = grouped.agg(agg_func)
    return result.rename(columns={agg_column: f"{agg_column}_{agg_func}"})


def top_n_rows(
    df: pd.DataFrame, column: str, n: int = 1, ascending: bool = False
) -> pd.DataFrame:
    _require_columns(df, [column])
    working = df.copy()
    working["_sort_key"] = _coerce_numeric_series(working[column])
    return (
        working.sort_values("_sort_key", ascending=ascending, na_position="last")
        .head(n)
        .drop(columns=["_sort_key"])
        .reset_index(drop=True)
    )


def lookup_rows(
    df: pd.DataFrame, query: str, columns: list[str] | None = None
) -> pd.DataFrame:
    if columns is None:
        columns = df.select_dtypes(include=["object", "string"]).columns.astype(str).tolist()
    if not columns:
        columns = [c for c in df.columns.astype(str) if not str(c).startswith("Unnamed")]
    _require_columns(df, columns)
    mask = pd.Series(False, index=df.index)
    for col in columns:
        mask |= df[col].astype(str).str.contains(str(query), case=False, na=False, regex=False)
    return df.loc[mask].copy()


def summary_stats(df: pd.DataFrame, column: str) -> dict:
    """Return summary statistics for a numeric column."""
    _require_columns(df, [column])
    series = _coerce_numeric_series(df[column]).dropna()
    if series.empty:
        return {"column": column, "count": 0, "sum": None, "mean": None, "min": None, "max": None}
    return {
        "column": column,
        "count": int(series.count()),
        "sum": float(series.sum()),
        "mean": float(series.mean()),
        "min": float(series.min()),
        "max": float(series.max()),
    }


def value_answer(
    df: pd.DataFrame,
    row_query: str,
    value_columns: list[str] | None = None,
    profile: dict | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Look up rows and return full row DataFrame plus structured metadata."""
    profile = profile or {}
    name_cols = profile.get("likely_name_columns", [])
    search_cols = name_cols + profile.get("text_columns", [])
    rows = lookup_rows(df, row_query, columns=search_cols or None)
    if rows.empty:
        return rows, {"row_query": row_query, "label": row_query, "row": {}, "row_count": 0}

    row = rows.iloc[0]
    label = row_query
    for col in name_cols:
        if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
            label = str(row[col]).strip()
            break

    metadata = {
        "row_query": row_query,
        "label": label,
        "row": {str(k): row[k] for k in row.index},
        "row_count": len(rows),
    }
    return rows.iloc[[0]].copy(), metadata


_DERIVE_OPERATORS = frozenset({"add", "subtract", "multiply", "divide", "percent", "abs_diff"})


def derive_column(
    df: pd.DataFrame,
    new_column: str,
    left_col: str,
    op: str,
    right_col: str | float | int,
) -> pd.DataFrame:
    """Add a derived numeric column without mutating the input DataFrame."""
    if op not in _DERIVE_OPERATORS:
        raise ValueError(f"지원하지 않는 derive op: {op!r}")

    result = df.copy()
    _require_columns(result, [left_col])
    left = _coerce_numeric_series(result[left_col])

    if isinstance(right_col, (int, float)):
        right = pd.Series(float(right_col), index=result.index)
    else:
        right_name = str(right_col)
        _require_columns(result, [right_name])
        right = _coerce_numeric_series(result[right_name])

    if op == "add":
        result[new_column] = left + right
    elif op == "subtract":
        result[new_column] = left - right
    elif op == "multiply":
        result[new_column] = left * right
    elif op in ("divide", "percent"):
        denom = right.replace(0, pd.NA)
        quotient = left / denom
        result[new_column] = quotient * 100 if op == "percent" else quotient
    elif op == "abs_diff":
        result[new_column] = (left - right).abs()

    return result


def compare_rows(df: pd.DataFrame, query_a: str, query_b: str, profile: dict | None = None) -> tuple[pd.DataFrame, str]:
    """Extension point for future 'A와 B 비교' queries."""
    rows_a = lookup_rows(df, query_a)
    rows_b = lookup_rows(df, query_b)
    combined = pd.concat([rows_a, rows_b]).drop_duplicates()
    message = f"'{query_a}'와 '{query_b}' 비교 결과입니다. (상세 비교는 추후 확장 예정)"
    return combined, message
