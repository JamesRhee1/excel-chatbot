"""Shared intent helpers for routing and execution."""

from __future__ import annotations

_ANALYSIS_TYPES = frozenset({"top_n", "sort", "aggregate", "summary_stats", "lookup", "filter", "value_answer"})
_EXCLUDE_HINTS = (
    "합계 제외", "소계 제외", "총계 제외", "합계 빼", "소계 빼", "제외하고",
    "합계 행", "소계 행", "다 합한", "합계는",
)
_INCLUDE_HINTS = ("합계 포함", "소계 포함", "합계도", "소계도", "합계까지", "전체 보여", "모든 행")
_TOTAL_HINTS = ("전체 합계", "전체합계", "총 합계", "합계 알려", "합계만", "합계 행")


def determine_row_types(user_message: str) -> list[str]:
    """Choose 행구분 filter values for 예실대비표 analysis."""
    msg = user_message.strip()
    if any(h in msg for h in _TOTAL_HINTS):
        return ["합계"]
    if "비목분류별 소계" in msg or ("소계" in msg and "별" in msg):
        return ["소계"]
    if any(h in msg for h in _INCLUDE_HINTS):
        return ["상세", "소계", "합계", "내부흡수액", "외부유출액"]
    return ["상세"]


def wants_exclude_summary(user_message: str, operations: list[dict], profile: dict | None = None) -> bool:
    """Whether to filter out summary rows before analysis."""
    msg = user_message.strip()
    if profile and profile.get("is_budget_table"):
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
    if profile and profile.get("is_budget_table"):
        row_types = determine_row_types(user_message)
        intent["operations"] = [{"type": "filter_row_type", "row_types": row_types}] + operations
    else:
        intent["operations"] = [{"type": "exclude_summary"}] + operations
    return intent
