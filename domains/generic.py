"""Generic Excel domain pack (fallback)."""

from __future__ import annotations

import re

import pandas as pd

from domains.base import DomainPack, SummaryRowConfig


def _looks_like_header_row(row: pd.Series) -> bool:
    values = [str(v).strip() for v in row.tolist() if pd.notna(v) and str(v).strip()]
    if not values:
        return False
    text_like = sum(1 for v in values if not re.fullmatch(r"[\d,.\-]+", v))
    return text_like >= max(2, len(values) // 2)


def normalize_generic_sheet(
    raw_df: pd.DataFrame,
    *,
    path: str = "",
    sheet_name: str | int = 0,
) -> pd.DataFrame:
    """Apply generic header detection and cleanup to a raw sheet."""
    from core.reader import coerce_numeric_columns, normalize_column_names

    if raw_df is None or raw_df.empty:
        return pd.DataFrame()

    if path:
        if _looks_like_header_row(raw_df.iloc[0]):
            df = pd.read_excel(path, sheet_name=sheet_name, header=0)
        else:
            df = raw_df.copy()
            df.columns = [f"col_{i}" for i in range(df.shape[1])]
    else:
        if _looks_like_header_row(raw_df.iloc[0]):
            df = raw_df.copy()
            df.columns = [str(v).strip() for v in raw_df.iloc[0].tolist()]
            df = df.iloc[1:].reset_index(drop=True)
        else:
            df = raw_df.copy()
            df.columns = [f"col_{i}" for i in range(df.shape[1])]

    df = normalize_column_names(df)
    return coerce_numeric_columns(df)


class GenericPack(DomainPack):
    def __init__(self) -> None:
        super().__init__(
            name="generic",
            synonyms={},
            summary_row_config=SummaryRowConfig(),
            example_queries=(),
            clarify_examples=(),
            compare_columns=(),
            name_columns=(),
            help_item_fallback="항목",
            help_amount_fallback="금액",
        )

    def detect(self, raw_df: pd.DataFrame) -> bool:
        return False

    def normalize_raw(
        self,
        raw_df: pd.DataFrame,
        *,
        path: str = "",
        sheet_name: str | int = 0,
    ) -> pd.DataFrame:
        return normalize_generic_sheet(raw_df, path=path, sheet_name=sheet_name)


GENERIC_PACK = GenericPack()
