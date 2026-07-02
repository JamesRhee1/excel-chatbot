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
    """Remove summary/total rows — uses 행구분 for budget tables, heuristics otherwise."""
    if "행구분" in df.columns:
        return df[df["행구분"] == "상세"].copy()
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


def filter_row_types(df: pd.DataFrame, row_types: list[str]) -> pd.DataFrame:
    """Filter rows by 행구분 values (예실대비표)."""
    if "행구분" not in df.columns:
        return df.copy()
    return df[df["행구분"].isin(row_types)].copy()


def build_help_message(profile: dict | None = None) -> str:
    """Build profile-aware help message with question examples."""
    lines = [
        "업로드된 엑셀 파일을 기준으로 아래와 같은 질문을 할 수 있습니다.",
        "",
        "**데이터 이해**",
        '- "데이터에 대해서 설명"',
        '- "니가 할 수 있는게 뭐야"',
        "",
        "**항목/금액 조회**",
    ]
    name_col = (profile or {}).get("likely_name_columns", ["비용명"])
    amount_cols = (profile or {}).get("likely_amount_columns", ["당년도예산"])
    name_example = name_col[0] if name_col else "항목명"
    amount_example = amount_cols[0] if amount_cols else "당년도예산"
    samples = (profile or {}).get("sample_values_by_column", {}).get(name_example, [])
    item_example = samples[0] if samples else "인쇄비"

    lines.extend(
        [
            f'- "{item_example}가 얼마야?"',
            f'- "{amount_example}이 가장 높은 행 찾아줘"',
            f'- "예산잔액이 남은 항목 보여줘"',
        ]
    )

    cat_col = (profile or {}).get("likely_category_columns", [])
    if cat_col:
        lines.extend(
            [
                "",
                "**집계/정렬/필터**",
                f'- "{cat_col[0]}별 {amount_example} 합계 보여줘"',
                f'- "{amount_example} 기준으로 큰 순서대로 보여줘"',
                f'- "{amount_example}이 0보다 큰 항목만 보여줘"',
            ]
        )

    lines.extend(
        [
            "",
            "**팁**",
            '- 정확한 컬럼명을 몰라도 됩니다. "당해예산" → "당년도예산"처럼 자동 해석합니다.',
            "- 모든 숫자는 pandas로 실제 계산한 결과입니다.",
        ]
    )
    return "\n".join(lines)


HELP_MESSAGE = build_help_message()


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
        "analysis_examples": _analysis_examples(profile),
    }


def describe_dataset(df: pd.DataFrame, profile: dict) -> str:
    """Build a natural-language summary of the dataset."""
    if profile.get("is_budget_table"):
        amount_cols = profile.get("likely_amount_columns", [])
        return (
            "이 파일은 **예실대비표** 형식의 예산·집행 현황 데이터입니다.\n\n"
            f"- **{profile['rows']}행**, **{profile['columns']}열**\n"
            "- 주요 기준 컬럼: `비목분류`, `비목코드`, `비용명`\n"
            f"- 주요 금액 컬럼: {', '.join(f'`{c}`' for c in amount_cols[:8])}\n"
            "- 기본 분석은 **상세 항목(행구분=상세)** 만 대상으로 합니다.\n"
            "- '전체 합계 알려줘'처럼 질문하면 합계 행을 사용합니다.\n\n"
            "**질문 예시**\n"
            '- "당해예산 중 가장 높은 행 찾아줘"\n'
            '- "인쇄비가 얼마지"\n'
            '- "비목분류별 당년도예산 합계 보여줘"'
        )

    info = describe_dataset_info(df, profile)
    lines = [
        f"이 데이터는 **{info['rows']}행**, **{info['columns']}열**로 구성되어 있습니다.",
        "",
        "**주요 컬럼**",
        ", ".join(f"`{c}`" for c in info["column_names"][:12]),
    ]
    if info["likely_amount_columns"]:
        lines.extend(["", "**금액/예산 관련 컬럼**", ", ".join(f"`{c}`" for c in info["likely_amount_columns"])])
    if info["likely_category_columns"]:
        lines.extend(["", "**분류 컬럼**", ", ".join(f"`{c}`" for c in info["likely_category_columns"])])
    if info["likely_name_columns"]:
        lines.extend(["", "**항목/이름 컬럼**", ", ".join(f"`{c}`" for c in info["likely_name_columns"])])
    if info["unnamed_columns"]:
        lines.extend(["", "**Unnamed 컬럼**", f"{len(info['unnamed_columns'])}개 (분석 시 우선순위 낮음)"])
    lines.extend(["", "**결측치**", "없음" if not info["missing_counts"] else str(len(info["missing_counts"])) + "개 컬럼에 결측 존재"])
    lines.extend(["", "**이 데이터로 해볼 수 있는 질문 예시**"])
    lines.extend([f"- {ex}" for ex in info["analysis_examples"]])
    return "\n".join(lines)


def _analysis_examples(profile: dict) -> list[str]:
    name_col = profile.get("likely_name_columns", ["항목"])
    amount_col = profile.get("likely_amount_columns", ["금액"])
    cat_col = profile.get("likely_category_columns", [])
    examples = [
        f'"{amount_col[0]}이 가장 높은 행 찾아줘"',
        f'"{name_col[0]}가 얼마야?"',
    ]
    if cat_col:
        examples.append(f'"{cat_col[0]}별 {amount_col[0]} 합계 보여줘"')
    examples.append('"데이터에 대해서 설명"')
    return examples


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


def compare_rows(df: pd.DataFrame, query_a: str, query_b: str, profile: dict | None = None) -> tuple[pd.DataFrame, str]:
    """Extension point for future 'A와 B 비교' queries."""
    rows_a = lookup_rows(df, query_a)
    rows_b = lookup_rows(df, query_b)
    combined = pd.concat([rows_a, rows_b]).drop_duplicates()
    message = f"'{query_a}'와 '{query_b}' 비교 결과입니다. (상세 비교는 추후 확장 예정)"
    return combined, message
