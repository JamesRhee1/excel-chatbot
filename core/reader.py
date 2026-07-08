"""Excel reading utilities using pandas/openpyxl."""

from __future__ import annotations

import re

import pandas as pd

from domains.registry import infer_domain_from_columns, match_pack


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


def load_excel_with_domain(path: str, sheet_name: str | int = 0) -> tuple[pd.DataFrame, str]:
    """Load an Excel sheet via domain pack detection and normalization."""
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    pack = match_pack(raw)
    df = pack.normalize_raw(raw, path=path, sheet_name=sheet_name)
    domain = infer_domain_from_columns([str(c) for c in df.columns.tolist()])
    return df, domain


def load_excel(path: str, sheet_name: str | int = 0) -> pd.DataFrame:
    """Load an Excel sheet; normalize via domain registry."""
    df, _ = load_excel_with_domain(path, sheet_name=sheet_name)
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
    from domains.registry import enrich_profile, infer_domain_from_columns

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    numeric_stats: dict[str, dict] = {}
    for col in numeric_cols:
        numeric_stats[col] = {
            "mean": float(df[col].mean()) if not df[col].isna().all() else None,
            "min": float(df[col].min()) if not df[col].isna().all() else None,
            "max": float(df[col].max()) if not df[col].isna().all() else None,
            "std": float(df[col].std()) if not df[col].isna().all() else None,
        }

    base = {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": df.columns.tolist(),
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "missing_counts": {col: int(df[col].isna().sum()) for col in df.columns},
        "numeric_stats": numeric_stats,
    }
    domain = infer_domain_from_columns(df.columns.tolist())
    return enrich_profile(base, domain)
