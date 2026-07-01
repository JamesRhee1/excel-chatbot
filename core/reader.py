"""Excel reading utilities using pandas/openpyxl."""

from __future__ import annotations

import pandas as pd


def load_excel(path: str, sheet_name: str | int = 0) -> pd.DataFrame:
    """Load an Excel sheet into a DataFrame.

    Args:
        path: Path to the Excel file.
        sheet_name: Sheet name or zero-based index (default: first sheet).

    Returns:
        DataFrame containing the sheet data.
    """
    return pd.read_excel(path, sheet_name=sheet_name)


def list_sheets(path: str) -> list[str]:
    """Return the names of all sheets in an Excel workbook.

    Args:
        path: Path to the Excel file.

    Returns:
        List of sheet names.
    """
    xl = pd.ExcelFile(path)
    return xl.sheet_names


def summarize(df: pd.DataFrame) -> dict:
    """Summarize a DataFrame's shape, columns, dtypes, missing values, and numeric stats.

    Args:
        df: Input DataFrame.

    Returns:
        Dictionary with row/column counts, column names, dtypes, missing counts,
        and basic statistics for numeric columns.
    """
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
    }
