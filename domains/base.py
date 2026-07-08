"""Domain pack interface for Excel sheet types."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class SummaryRowConfig:
    """How to identify detail vs summary rows in a normalized sheet."""

    row_type_column: str | None = None
    detail_row_type: str | None = None
    total_row_types: tuple[str, ...] = ()
    all_analysis_row_types: tuple[str, ...] = ()


@dataclass
class DomainPack:
    """Domain-specific detection, normalization, and vocabulary."""

    name: str
    synonyms: dict[str, str] = field(default_factory=dict)
    summary_row_config: SummaryRowConfig = field(default_factory=SummaryRowConfig)
    example_queries: tuple[str, ...] = ()
    clarify_examples: tuple[str, ...] = ()
    compare_columns: tuple[str, ...] = ()
    name_columns: tuple[str, ...] = ()
    value_primary_cols: tuple[str, ...] = ()
    value_secondary_cols: tuple[str, ...] = ()
    default_display_cols: tuple[str, ...] = ()
    top_n_extra_cols: tuple[str, ...] = ()
    column_labels: dict[str, str] = field(default_factory=dict)
    multi_display_cols: tuple[str, ...] = ()
    multi_example_queries: tuple[str, ...] = ()
    normalized_signature_columns: tuple[str, ...] = ()
    help_item_fallback: str = "항목"
    help_amount_fallback: str = "금액"
    balance_column_fallback: str | None = None
    synonym_tip: str | None = None
    describe_label: str | None = None

    def detect(self, raw_df: pd.DataFrame) -> bool:
        return False

    def normalize_raw(
        self,
        raw_df: pd.DataFrame,
        *,
        path: str = "",
        sheet_name: str | int = 0,
    ) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} pack did not implement normalize_raw")

    def matches_normalized_columns(self, column_names: list[str]) -> bool:
        if not self.normalized_signature_columns:
            return False
        cols = set(column_names)
        return all(col in cols for col in self.normalized_signature_columns)
