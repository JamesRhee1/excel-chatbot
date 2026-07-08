"""Backward-compatible re-exports for domain-driven sheet normalization."""

from __future__ import annotations

import pandas as pd

from domains.registry import match_pack, registered_packs


def normalize_budget_sheet(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw sheet using the matched domain pack."""
    return match_pack(raw_df).normalize_raw(raw_df)


def is_specialized_domain_sheet(raw_df: pd.DataFrame) -> bool:
    """Return True when a specialized domain pack detects the sheet."""
    for pack in registered_packs():
        if pack.name == "generic":
            continue
        if pack.detect(raw_df):
            return True
    return False


def _primary_specialized_pack():
    for pack in registered_packs():
        if pack.name != "generic":
            return pack
    raise RuntimeError("no specialized domain pack registered")


OUTPUT_COLUMNS = list(_primary_specialized_pack().output_columns)

__all__ = ["OUTPUT_COLUMNS", "is_specialized_domain_sheet", "normalize_budget_sheet"]
