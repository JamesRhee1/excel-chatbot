"""Rule-based query routing before LLM planner."""

from __future__ import annotations

import re


_HELP_KEYWORDS = (
    "할 수 있는", "할수있는", "할 수 있", "기능", "도움말", "뭘 할", "무엇을 할", "예시",
)
_DESCRIBE_KEYWORDS = (
    "데이터에 대해서 설명", "데이터 설명", "데이터 요약", "데이터에 대해",
    "무슨 데이터", "어떤 데이터", "컬럼 설명",
)
_TOTAL_HINTS = ("전체 합계", "전체합계", "총 합계", "합계 알려", "합계만", "합계 행")
_TOP_MAX_KEYWORDS = ("가장 높은", "최대", "제일 큰", "가장 큰", "최댓값", "가장 많은", "많이 남은")
_TOP_MIN_KEYWORDS = ("가장 낮은", "최소", "제일 작은", "가장 작은", "최솟값", "가장 적은")
_LOOKUP_KEYWORDS = ("찾아줘", "찾아", "검색", "어디 있어", "보여줘")

_AGG_GROUP_PATTERN = re.compile(
    r"(.+?)(?:별|마다)(?:\s+(.+?))?\s*(합계|평균|개수|최대|최소|총)(?:\s*보여)?"
)
_SORT_DESC_PATTERN = re.compile(r"(.+?)(?:기준|으로|로).*(큰\s*순|내림차순|높은\s*순|큰\s*순서)")
_SORT_ASC_PATTERN = re.compile(r"(.+?)(?:기준|으로|로).*(작은\s*순|오름차순|낮은\s*순)")
_FILTER_NUM_PATTERN = re.compile(
    r"(.+?)(?:이|가)\s*(\d+(?:\.\d+)?)\s*보다\s*(큰|작은|이상|이하|초과|미만)"
)
_FILTER_POSITIVE_PATTERN = re.compile(r"(.+?)(?:이|가)\s*0\s*보다\s*큰")
_REMAINING_BALANCE = re.compile(r"(예산잔액|잔액).*(남|있는)|남은.*(예산|잔액)")


def _synonyms(profile: dict) -> dict[str, str]:
    return profile.get("domain_synonyms") or {}


def _uses_row_types(profile: dict) -> bool:
    cfg = profile.get("summary_row_config") or {}
    return bool(cfg.get("row_type_column") and cfg.get("detail_row_type"))


def _total_row_types(profile: dict) -> list[str]:
    cfg = profile.get("summary_row_config") or {}
    return list(cfg.get("total_row_types") or ["합계"])


def _balance_column(profile: dict) -> str | None:
    return profile.get("domain_balance_column_fallback")


def route_query(user_query: str, profile: dict) -> dict | None:
    """Match common query patterns without calling the LLM."""
    return route_intent(user_query, profile)


def route_intent(user_message: str, profile: dict) -> dict | None:
    msg = user_message.strip()
    if not msg:
        return None

    if _is_help_query(msg):
        return _intent("message", [{"type": "help"}])
    if _is_describe_query(msg):
        return _intent("message", [{"type": "describe_dataset"}])

    total_intent = _try_total_row(msg, profile)
    if total_intent:
        return total_intent

    top_intent = _try_top_n(msg, profile)
    if top_intent:
        return top_intent

    filter_intent = _try_filter(msg, profile)
    if filter_intent:
        return filter_intent

    sort_intent = _try_sort(msg, profile)
    if sort_intent:
        return sort_intent

    agg_intent = _try_aggregate(msg, profile)
    if agg_intent:
        return agg_intent

    value_intent = _try_value_answer(msg)
    if value_intent:
        return value_intent

    lookup_intent = _try_lookup(msg, profile)
    if lookup_intent:
        return lookup_intent

    return None


def _intent(answer_type: str, operations: list[dict], message: str = "") -> dict:
    return {
        "answer_type": answer_type,
        "operations": operations,
        "message": message,
        "final_response_instruction": "",
    }


def _is_help_query(msg: str) -> bool:
    if any(kw in msg for kw in _HELP_KEYWORDS):
        return True
    if re.search(r"(니가|너는|넌|챗봇).{0,12}(뭐야|뭐니|뭐지|뭔데)", msg):
        return True
    if re.search(r"뭐(야|니|지|냐)\s*$", msg) and not _has_data_query_hint(msg):
        return True
    return False


def _has_data_query_hint(msg: str) -> bool:
    return any(h in msg for h in ("얼마", "예산", "금액", "찾", "높", "낮", "필터", "정렬", "합계", "평균", "보여"))


def _is_describe_query(msg: str) -> bool:
    return any(kw in msg for kw in _DESCRIBE_KEYWORDS)


def _try_value_answer(msg: str) -> dict | None:
    if any(kw in msg for kw in _TOP_MAX_KEYWORDS + _TOP_MIN_KEYWORDS):
        return None
    if "별" in msg and any(w in msg for w in ("합계", "평균", "개수", "총")):
        return None
    if "기준" in msg and any(w in msg for w in ("순", "정렬")):
        return None
    if "얼마" not in msg:
        return None

    for pattern in (
        re.compile(r"(.+?)(?:이|가)\s*얼마"),
        re.compile(r"(.+?)\s*(?:금액|예산|비용)\s*(?:이|가)?\s*얼마"),
    ):
        match = pattern.search(msg)
        if match:
            query = match.group(1).strip(" ?.,'\"")
            query = re.sub(r"^(그럼|그러면|혹시)\s*", "", query)
            if len(query) >= 2:
                return _intent("mixed", [{"type": "value_answer", "row_query": query}])
    return None


def _try_total_row(msg: str, profile: dict) -> dict | None:
    if not any(h in msg for h in _TOTAL_HINTS):
        return None
    if _uses_row_types(profile):
        return _intent("mixed", [{"type": "filter_row_type", "row_types": _total_row_types(profile)}])
    return _intent("mixed", [{"type": "lookup", "query": "합계"}])


def _try_filter(msg: str, profile: dict) -> dict | None:
    if _REMAINING_BALANCE.search(msg):
        col = _balance_column(profile) or _extract_column_hint(msg, profile) or "잔액"
        return _intent("dataframe", [{"type": "filter", "column": col, "op": ">", "value": 0}])

    match = _FILTER_POSITIVE_PATTERN.search(msg)
    if match:
        col = _extract_column_hint(match.group(1), profile) or match.group(1).strip()
        return _intent("dataframe", [{"type": "filter", "column": col, "op": ">", "value": 0}])

    match = _FILTER_NUM_PATTERN.search(msg)
    if match:
        col = _extract_column_hint(match.group(1), profile) or match.group(1).strip()
        value = float(match.group(2)) if "." in match.group(2) else int(match.group(2))
        op_map = {"큰": ">", "초과": ">", "작은": "<", "미만": "<", "이상": ">=", "이하": "<="}
        op = op_map.get(match.group(3), ">")
        return _intent("dataframe", [{"type": "filter", "column": col, "op": op, "value": value}])
    return None


def _try_sort(msg: str, profile: dict) -> dict | None:
    for pattern, ascending in ((_SORT_ASC_PATTERN, True), (_SORT_DESC_PATTERN, False)):
        match = pattern.search(msg)
        if match:
            col = _extract_column_hint(match.group(1), profile) or match.group(1).strip()
            return _intent("dataframe", [{"type": "sort", "column": col, "ascending": ascending}])
    return None


def _try_top_n(msg: str, profile: dict) -> dict | None:
    ascending = False
    n = 1
    matched = None
    for kw in _TOP_MIN_KEYWORDS:
        if kw in msg:
            ascending, matched = True, kw
            break
    if not matched:
        for kw in _TOP_MAX_KEYWORDS:
            if kw in msg:
                ascending, matched = False, kw
                break
    if not matched:
        return None

    num_match = re.search(r"(\d+)\s*개", msg)
    if num_match:
        n = int(num_match.group(1))

    column_hint = _extract_column_hint(msg, profile)
    if not column_hint:
        return None

    return _intent(
        "mixed",
        [{"type": "top_n", "column": column_hint, "n": n, "ascending": ascending}],
    )


def _try_lookup(msg: str, profile: dict) -> dict | None:
    if not any(kw in msg for kw in _LOOKUP_KEYWORDS):
        return None
    if "얼마" in msg or ("별" in msg and "합계" in msg):
        return None
    if any(k in msg for k in ("가장", "최대", "최소", "합계", "평균", "기준")):
        return None
    cleaned = re.sub(r"(찾아줘|찾아|검색|보여줘|어디 있어|해줘|주세요)", "", msg).strip()
    if len(cleaned) >= 2:
        return _intent("dataframe", [{"type": "lookup", "query": cleaned}])
    return None


def _try_aggregate(msg: str, profile: dict) -> dict | None:
    match = _AGG_GROUP_PATTERN.search(msg)
    if not match:
        return None

    group_hint = match.group(1).strip()
    agg_hint = (match.group(2) or "").strip()
    metric = match.group(3)
    agg_func = {"합계": "sum", "총": "sum", "평균": "mean", "개수": "count", "최대": "max", "최소": "min"}.get(
        metric, "sum"
    )

    group_col = _extract_column_hint(group_hint, profile) or group_hint
    agg_col = _extract_column_hint(agg_hint, profile) if agg_hint else _guess_agg_column(msg, profile)
    if not agg_col:
        return None

    return _intent(
        "dataframe",
        [{"type": "aggregate", "group_by": [group_col], "agg_column": agg_col, "agg_func": agg_func}],
    )


def _extract_column_hint(msg: str, profile: dict) -> str | None:
    column_names = profile.get("column_names", [])
    unnamed = set(profile.get("unnamed_columns", []))
    synonyms = _synonyms(profile)

    for col in column_names:
        if col not in unnamed and col in msg:
            return col
    for expr in synonyms:
        if expr in msg:
            return expr
    for col in profile.get("likely_amount_columns", []) + profile.get("likely_category_columns", []):
        if col in msg:
            return col
    for col in column_names:
        if col in unnamed:
            continue
        for part in re.split(r"[\s,·]+", col):
            if len(part) >= 2 and part in msg:
                return col

    cleaned = re.sub(
        r"(찾아|보여|알려|줘|주세요|행을|값인|중에|에서|으로|로|의|을|를|이|가|은|는|에|와|과|가장|높은|낮은|큰|작은|최대|최소|제일|많이|남은|항목|보다|큰|합계)",
        " ",
        msg,
    )
    for token in [t for t in cleaned.split() if len(t) >= 2]:
        for col in column_names:
            if col not in unnamed and (token in col or col in token):
                return col
        if token in synonyms:
            return token
    return None


def _guess_agg_column(msg: str, profile: dict) -> str | None:
    hint = _extract_column_hint(msg, profile)
    if hint and hint in profile.get("likely_amount_columns", []):
        return hint
    likely = profile.get("likely_amount_columns", [])
    return likely[0] if likely else None
