"""Excel reading utilities using pandas/openpyxl."""

from __future__ import annotations

import re

import pandas as pd

from core.budget_table_normalizer import is_budget_comparison_sheet, normalize_budget_sheet


def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names: strip whitespace, collapse internal spaces."""
    result = df.copy()
    new_columns: list[str] = []
    for col in result.columns:
        name = str(col).strip()
        name = re.sub(r"\s+", " ", name)
        new_columns.append(name)
    result.columns = new_columns
    return result


def coerce_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Convert string columns with numeric-looking values (incl. comma amounts)."""
    result = df.copy()
    for col in result.columns:
        if pd.api.types.is_numeric_dtype(result[col]):
            continue
        series = result[col]
        if series.dtype not in ("object", "string"):
            continue
        cleaned = (
            series.astype(str)
            .str.replace(",", "", regex=False)
            .str.replace("원", "", regex=False)
            .str.strip()
        )
        numeric = pd.to_numeric(cleaned, errors="coerce")
        if numeric.notna().sum() >= max(1, len(series.dropna()) * 0.5):
            result[col] = numeric
    return result


def load_excel(path: str, sheet_name: str | int = 0) -> pd.DataFrame:
    """Load an Excel sheet; normalize 예실대비표 or apply generic cleanup."""
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)

    if is_budget_comparison_sheet(raw):
        return normalize_budget_sheet(raw)

    # Generic table: use first row as header if it looks like headers
    if _looks_like_header_row(raw.iloc[0]):
        df = pd.read_excel(path, sheet_name=sheet_name, header=0)
    else:
        df = raw.copy()
        df.columns = [f"col_{i}" for i in range(df.shape[1])]

    df = normalize_column_names(df)
    df = coerce_numeric_columns(df)
    return df


def _looks_like_header_row(row: pd.Series) -> bool:
    values = [str(v).strip() for v in row.tolist() if pd.notna(v) and str(v).strip()]
    if not values:
        return False
    text_like = sum(1 for v in values if not re.fullmatch(r"[\d,.\-]+", v))
    return text_like >= max(2, len(values) // 2)


def list_sheets(path: str) -> list[str]:
    """Return the names of all sheets in an Excel workbook."""
    xl = pd.ExcelFile(path)
    return xl.sheet_names


def summarize(df: pd.DataFrame) -> dict:
    """Summarize a DataFrame's shape, columns, dtypes, missing values, and numeric stats."""
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    numeric_stats: dict[str, dict] = {}
    for col in numeric_cols:
        numeric_stats[col] = {
            "mean": float(df[col].mean()) if not df[col].isna().all() else None,
            "min": float(df[col].min()) if not df[col].isna().all() else None,
            "max": float(df[col].max()) if not df[col].isna().all() else None,
            "std": float(df[col].std()) if not df[col].isna().all() else None,
        }

    return {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": df.columns.tolist(),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing_counts": {col: int(df[col].isna().sum()) for col in df.columns},
        "numeric_stats": numeric_stats,
        "is_budget_table": "행구분" in df.columns and "비목분류" in df.columns,
    }
