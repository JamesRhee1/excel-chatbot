"""Shared intent helpers for routing and execution."""

from __future__ import annotations

_ANALYSIS_TYPES = frozenset({"top_n", "sort", "aggregate", "summary_stats", "lookup", "filter", "value_answer"})
_EXCLUDE_HINTS = (
    "합계 제외", "소계 제외", "총계 제외", "합계 빼", "소계 빼", "제외하고",
    "합계 행", "소계 행", "다 합한", "합계는",
)
_INCLUDE_HINTS = ("합계 포함", "소계 포함", "합계도", "소계도", "합계까지", "전체 보여", "모든 행")
_TOTAL_HINTS = ("전체 합계", "전체합계", "총 합계", "합계 알려", "합계만", "합계 행")


def _summary_config(profile: dict | None) -> dict:
    return (profile or {}).get("summary_row_config") or {}


def determine_row_types(user_message: str, profile: dict | None = None) -> list[str]:
    """Choose row-type filter values when the domain defines them."""
    msg = user_message.strip()
    cfg = _summary_config(profile)
    all_types = list(cfg.get("all_analysis_row_types") or ["상세"])
    total_types = list(cfg.get("total_row_types") or ["합계"])

    if any(h in msg for h in _TOTAL_HINTS):
        return total_types
    if "소계" in msg and "별" in msg:
        return ["소계"]
    if any(h in msg for h in _INCLUDE_HINTS):
        return all_types
    detail = cfg.get("detail_row_type")
    return [detail] if detail else ["상세"]


def wants_exclude_summary(user_message: str, operations: list[dict], profile: dict | None = None) -> bool:
    """Whether to filter out summary rows before analysis."""
    msg = user_message.strip()
    cfg = _summary_config(profile)
    if cfg.get("row_type_column") and cfg.get("detail_row_type"):
        if any(h in msg for h in _TOTAL_HINTS):
            return False
        if any(h in msg for h in _INCLUDE_HINTS):
            return False
        if any(op.get("type") in _ANALYSIS_TYPES for op in operations):
            return True
        return False

    if any(h in msg for h in _INCLUDE_HINTS):
        return False
    if any(h in msg for h in _EXCLUDE_HINTS):
        return True
    if any(op.get("type") in _ANALYSIS_TYPES for op in operations):
        return True
    return False


def prepend_exclude_summary(intent: dict, user_message: str, profile: dict | None = None) -> dict:
    """Insert row-type or summary exclusion before analysis operations."""
    operations = intent.get("operations") or []
    if not operations:
        return intent
    if not wants_exclude_summary(user_message, operations, profile):
        return intent
    first_type = operations[0].get("type")
    if first_type in ("exclude_summary", "filter_row_type"):
        return intent
    if not any(op.get("type") in _ANALYSIS_TYPES for op in operations):
        return intent

    intent = dict(intent)
    cfg = _summary_config(profile)
    if cfg.get("row_type_column") and cfg.get("detail_row_type"):
        row_types = determine_row_types(user_message, profile)
        intent["operations"] = [{"type": "filter_row_type", "row_types": row_types}] + operations
    else:
        intent["operations"] = [{"type": "exclude_summary"}] + operations
    return intent
