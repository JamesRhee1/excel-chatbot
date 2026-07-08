"""Rule-based routing for multi-file Excel queries."""

from __future__ import annotations

import re

_COMBINE_KEYWORDS = ("통합", "합쳐", "합치", "통합자료", "합쳐줘", "통합해")
_FILE_LEVEL_KEYWORDS = ("파일별", "각 파일", "파일 마다", "파일마다")
_OVERALL_KEYWORDS = ("전체 파일", "통합 데이터", "전체 통합", "모든 파일")
_COMPARE_KEYWORDS = ("비교", "대비")
_TOP_MAX_KEYWORDS = ("가장 높은", "가장 큰", "최대", "제일 큰", "최고")
_TOP_MIN_KEYWORDS = ("가장 낮은", "가장 작은", "최소", "제일 작은")
_SUMMARY_KEYWORDS = ("요약", "집행률 비교", "파일별 집행률")


def _synonyms(profile: dict | None) -> dict[str, str]:
    return (profile or {}).get("domain_synonyms") or {}


def _known_columns(profile: dict | None) -> frozenset[str]:
    profile = profile or {}
    cols = set(_synonyms(profile).keys()) | set(_synonyms(profile).values())
    cols.update(profile.get("column_names", []))
    cols.update(profile.get("domain_compare_columns", []))
    cols.update(profile.get("likely_amount_columns", []))
    return frozenset(cols)


def route_multi_query(user_query: str, combined_profile: dict | None = None) -> dict | None:
    """Match multi-file query patterns without calling the LLM."""
    msg = user_query.strip()
    if not msg:
        return None

    if _is_combine_query(msg):
        return _intent("combine_dataset")

    summarize = _try_summarize_by_file(msg, combined_profile)
    if summarize:
        return summarize

    compare_intent = _try_compare_item(msg, combined_profile)
    if compare_intent:
        return compare_intent

    top_by_file = _try_top_n_by_file(msg, combined_profile)
    if top_by_file:
        return top_by_file

    top_overall = _try_top_n_overall(msg, combined_profile)
    if top_overall:
        return top_overall

    if _is_multi_summary(msg):
        return _intent("multi_summary")

    return None


def _intent(op_type: str, **kwargs) -> dict:
    operation = {"type": op_type, **kwargs}
    return {
        "answer_type": "mixed",
        "operations": [operation],
        "message": "",
    }


def _is_combine_query(msg: str) -> bool:
    if any(kw in msg for kw in _COMBINE_KEYWORDS):
        return True
    if re.search(r"(이|여러)\s*파일", msg) and any(k in msg for k in ("통합", "합쳐", "합치")):
        return True
    return False


def _is_multi_summary(msg: str) -> bool:
    return any(kw in msg for kw in _SUMMARY_KEYWORDS) and "파일" in msg


def _extract_column_hint(msg: str, profile: dict | None) -> str | None:
    profile = profile or {}
    for expr, canonical in _synonyms(profile).items():
        if expr in msg:
            return canonical
    for col in profile.get("domain_compare_columns", []) + profile.get("likely_amount_columns", []):
        if col in msg:
            return col
    for col in profile.get("column_names", []):
        if col in msg:
            return col
    return None


def _extract_n(msg: str, default: int = 1) -> int:
    match = re.search(r"(\d+)\s*개", msg)
    return int(match.group(1)) if match else default


def _is_ascending(msg: str) -> bool:
    return any(kw in msg for kw in _TOP_MIN_KEYWORDS)


def _try_compare_item(msg: str, profile: dict | None) -> dict | None:
    if not any(kw in msg for kw in _COMPARE_KEYWORDS + _FILE_LEVEL_KEYWORDS):
        return None
    if not any(kw in msg for kw in _FILE_LEVEL_KEYWORDS + ("파일별",)):
        if "파일" not in msg:
            return None

    patterns = [
        re.compile(r"(.+?)(?:을|를)\s*파일별(?:로)?\s*비교"),
        re.compile(r"(.+?)\s*파일별(?:로)?\s*비교"),
        re.compile(r"파일별\s*(.+?)\s*비교"),
    ]
    known = _known_columns(profile)
    for pattern in patterns:
        match = pattern.search(msg)
        if match:
            item = match.group(1).strip(" ?.,'\"")
            item = re.sub(r"^(이|그|해당)\s*", "", item)
            if len(item) >= 2 and item not in known and _extract_column_hint(item, profile) is None:
                return _intent("compare_item_across_files", item_query=item)
    return None


def _try_summarize_by_file(msg: str, profile: dict | None) -> dict | None:
    if not any(kw in msg for kw in _FILE_LEVEL_KEYWORDS):
        return None
    if not any(kw in msg for kw in ("합계", "비교", "집행률", "평균", "총")):
        return None

    col = _extract_column_hint(msg, profile)
    if not col:
        return None

    if col == "집행률" and "비교" in msg:
        return _intent("multi_summary")

    return _intent("summarize_by_file", value_column=col)


def _try_top_n_by_file(msg: str, profile: dict | None) -> dict | None:
    if not any(kw in msg for kw in _FILE_LEVEL_KEYWORDS + ("각 파일",)):
        return None
    if not any(kw in msg for kw in _TOP_MAX_KEYWORDS + _TOP_MIN_KEYWORDS + ("가장", "최고", "top")):
        return None

    col = _extract_column_hint(msg, profile)
    if not col:
        return None

    ascending = _is_ascending(msg)
    n = _extract_n(msg, default=1)
    return _intent(
        "top_n_by_file",
        value_column=col,
        n=n,
        ascending=ascending,
    )


def _try_top_n_overall(msg: str, profile: dict | None) -> dict | None:
    if not any(kw in msg for kw in _OVERALL_KEYWORDS):
        return None
    if not any(kw in msg for kw in _TOP_MAX_KEYWORDS + _TOP_MIN_KEYWORDS + ("가장", "큰", "높은")):
        return None

    col = _extract_column_hint(msg, profile)
    if not col and "잔액" in msg:
        profile = profile or {}
        balance_cols = [c for c in profile.get("domain_compare_columns", []) if "잔액" in c]
        col = balance_cols[0] if balance_cols else None
    if not col:
        return None

    ascending = _is_ascending(msg)
    n = _extract_n(msg, default=5)
    return _intent(
        "top_n_overall",
        value_column=col,
        n=n,
        ascending=ascending,
    )
