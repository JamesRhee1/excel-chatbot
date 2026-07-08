"""Backward-compatible re-exports for budget table normalization."""

from domains.budget_comparison import (
    OUTPUT_COLUMNS,
    detect_budget_sheet as is_budget_comparison_sheet,
    normalize_budget_sheet,
)

__all__ = ["OUTPUT_COLUMNS", "is_budget_comparison_sheet", "normalize_budget_sheet"]
