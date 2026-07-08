"""Operations on combined multi-file DataFrames."""

from __future__ import annotations

import pandas as pd


def _summary_config(profile: dict | None) -> dict:
    return (profile or {}).get("summary_row_config") or {}


def _filter_row_type(
    df: pd.DataFrame,
    row_type: str | None,
    profile: dict | None = None,
) -> pd.DataFrame:
    if row_type is None:
        return df.copy()
    cfg = _summary_config(profile)
    row_type_col = cfg.get("row_type_column")
    if row_type_col and row_type_col in df.columns:
        return df[df[row_type_col] == row_type].copy()
    return df.copy()


def _require_source_file(df: pd.DataFrame) -> None:
    if "source_file" not in df.columns:
        raise ValueError("통합 데이터에 source_file 컬럼이 없습니다.")


def _compare_columns(df: pd.DataFrame, profile: dict | None) -> list[str]:
    profile = profile or {}
    configured = profile.get("domain_compare_columns") or []
    cols = [c for c in configured if c in df.columns]
    if cols:
        return cols
    return profile.get("likely_amount_columns", [])[:7]


def _name_columns(df: pd.DataFrame, profile: dict | None) -> list[str]:
    profile = profile or {}
    configured = profile.get("domain_name_columns") or []
    name_cols = [c for c in configured if c in df.columns]
    if name_cols:
        return name_cols
    return [
        c
        for c in df.select_dtypes(include=["object", "string"]).columns.astype(str)
        if c not in ("source_file", "source_sheet")
        and c != _summary_config(profile).get("row_type_column")
    ]


def summarize_by_file(
    combined_df: pd.DataFrame,
    value_column: str,
    row_type: str | None = None,
    profile: dict | None = None,
) -> pd.DataFrame:
    """Aggregate value_column by source_file."""
    _require_source_file(combined_df)
    if value_column not in combined_df.columns:
        raise KeyError(value_column)

    detail_type = row_type or _summary_config(profile).get("detail_row_type")
    work = _filter_row_type(combined_df, detail_type, profile=profile)
    grouped = (
        work.groupby("source_file", as_index=False)[value_column]
        .agg(sum="sum", mean="mean", max="max", min="min", count="count")
    )
    grouped = grouped.rename(
        columns={
            "sum": f"{value_column}_sum",
            "mean": f"{value_column}_mean",
            "max": f"{value_column}_max",
            "min": f"{value_column}_min",
            "count": f"{value_column}_count",
        }
    )
    return grouped


def compare_item_across_files(
    combined_df: pd.DataFrame,
    item_query: str,
    value_columns: list[str] | None = None,
    profile: dict | None = None,
) -> pd.DataFrame:
    """Find item_query in configured name columns and compare across files."""
    _require_source_file(combined_df)
    value_columns = value_columns or _compare_columns(combined_df, profile)
    if not value_columns:
        raise ValueError("비교할 금액 컬럼이 없습니다.")

    name_cols = _name_columns(combined_df, profile)
    mask = pd.Series(False, index=combined_df.index)
    for col in name_cols:
        mask |= combined_df[col].astype(str).str.contains(item_query, case=False, na=False, regex=False)

    rows = combined_df.loc[mask].copy()
    if rows.empty:
        return rows

    detail_type = _summary_config(profile).get("detail_row_type")
    row_type_col = _summary_config(profile).get("row_type_column")
    if detail_type and row_type_col and row_type_col in rows.columns:
        detail = rows[rows[row_type_col] == detail_type]
        if not detail.empty:
            rows = detail

    display_cols = ["source_file"] + name_cols + value_columns
    display_cols = [c for c in display_cols if c in rows.columns]
    display_cols = list(dict.fromkeys(display_cols))

    if "source_file" in rows.columns:
        rows = rows.drop_duplicates(subset=["source_file"], keep="first")

    return rows[display_cols].reset_index(drop=True)


def top_n_by_file(
    combined_df: pd.DataFrame,
    value_column: str,
    n: int = 1,
    ascending: bool = False,
    row_type: str | None = None,
    profile: dict | None = None,
) -> pd.DataFrame:
    """Top n rows per source_file by value_column."""
    _require_source_file(combined_df)
    if value_column not in combined_df.columns:
        raise KeyError(value_column)

    detail_type = row_type or _summary_config(profile).get("detail_row_type")
    work = _filter_row_type(combined_df, detail_type, profile=profile)
    if work.empty:
        return work

    parts: list[pd.DataFrame] = []
    for source_file, group in work.groupby("source_file", sort=False):
        ranked = group.sort_values(value_column, ascending=ascending, na_position="last").head(n)
        parts.append(ranked)

    if not parts:
        return work.iloc[0:0].copy()
    return pd.concat(parts, ignore_index=True)


def top_n_overall(
    combined_df: pd.DataFrame,
    value_column: str,
    n: int = 5,
    ascending: bool = False,
    row_type: str | None = None,
    profile: dict | None = None,
) -> pd.DataFrame:
    """Top n rows across all files by value_column."""
    if value_column not in combined_df.columns:
        raise KeyError(value_column)

    detail_type = row_type or _summary_config(profile).get("detail_row_type")
    work = _filter_row_type(combined_df, detail_type, profile=profile)
    return (
        work.sort_values(value_column, ascending=ascending, na_position="last")
        .head(n)
        .reset_index(drop=True)
    )


def build_multi_file_summary(combined_df: pd.DataFrame, profile: dict | None = None) -> dict:
    """Build summary statistics for a combined dataset."""
    _require_source_file(combined_df)
    cfg = _summary_config(profile)
    row_type_col = cfg.get("row_type_column")
    detail_type = cfg.get("detail_row_type")

    detail_count = 0
    if detail_type and row_type_col and row_type_col in combined_df.columns:
        detail_count = int((combined_df[row_type_col] == detail_type).sum())

    rows_by_file = combined_df.groupby("source_file").size().to_dict()
    detail_by_file: dict[str, int] = {}
    if detail_type and row_type_col and row_type_col in combined_df.columns:
        detail_by_file = (
            combined_df[combined_df[row_type_col] == detail_type]
            .groupby("source_file")
            .size()
            .to_dict()
        )

    budget_sum_by_file: dict[str, float] = {}
    execution_sum_by_file: dict[str, float] = {}
    balance_sum_by_file: dict[str, float] = {}
    execution_rate_by_file: dict[str, float] = {}

    work = combined_df
    if detail_type and row_type_col and row_type_col in work.columns:
        work = work[work[row_type_col] == detail_type]

    amount_cols = (profile or {}).get("likely_amount_columns") or []
    budget_col = next((c for c in amount_cols if c in work.columns), None)
    execution_col = next(
        (c for c in amount_cols if "집행" in c and c in work.columns),
        None,
    )
    balance_candidates = (profile or {}).get("domain_compare_columns") or amount_cols
    balance_col = next(
        (c for c in balance_candidates if "잔액" in c and c in work.columns),
        None,
    )

    if budget_col:
        budget_sum_by_file = work.groupby("source_file")[budget_col].sum().to_dict()
    if execution_col:
        execution_sum_by_file = work.groupby("source_file")[execution_col].sum().to_dict()
    if balance_col:
        balance_sum_by_file = work.groupby("source_file")[balance_col].sum().to_dict()

    if "집행률" in combined_df.columns and detail_type and row_type_col:
        execution_rate_by_file = (
            combined_df[combined_df[row_type_col] == detail_type]
            .groupby("source_file")["집행률"]
            .mean()
            .to_dict()
        )
    elif budget_sum_by_file and execution_sum_by_file:
        for fname in budget_sum_by_file:
            budget = budget_sum_by_file.get(fname, 0) or 0
            execution = execution_sum_by_file.get(fname, 0) or 0
            execution_rate_by_file[fname] = (execution / budget) if budget else 0.0

    return {
        "file_count": combined_df["source_file"].nunique(),
        "total_rows": len(combined_df),
        "detail_rows": detail_count,
        "rows_by_file": rows_by_file,
        "detail_rows_by_file": detail_by_file,
        "budget_sum_by_file": budget_sum_by_file,
        "execution_sum_by_file": execution_sum_by_file,
        "balance_sum_by_file": balance_sum_by_file,
        "execution_rate_by_file": execution_rate_by_file,
    }
