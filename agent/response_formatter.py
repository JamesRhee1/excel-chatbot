"""Single place for user-facing messages and display DataFrame shaping."""

from __future__ import annotations

import re

import pandas as pd

from agent.presentation import analysis_examples, build_help_message
from core.operations import _format_amount, describe_dataset_info
from llm.intent import UNKNOWN_MESSAGE

_FULL_DETAIL_KEYWORDS = ("자세히", "전체 컬럼", "모든 컬럼", "전체 보여", "모든 컬럼")

_INTERNAL_LOG_MARKERS = (
    "분석 대상으로 선정",
    "합계/소계",
    "상세 항목",
    "필터링했습니다",
    "operation",
    "lookup_rows",
)


def _profile_cols(profile: dict, key: str, *fallback_keys: str) -> tuple[str, ...]:
    values = profile.get(key)
    if values:
        return tuple(values)
    for fallback in fallback_keys:
        alt = profile.get(fallback)
        if alt:
            return tuple(alt)
    return ()


def _value_primary_cols(profile: dict) -> tuple[str, ...]:
    return _profile_cols(profile, "domain_value_primary_cols", "likely_amount_columns")


def _value_secondary_cols(profile: dict) -> tuple[str, ...]:
    return _profile_cols(profile, "domain_value_secondary_cols")


def _default_display_cols(profile: dict) -> tuple[str, ...]:
    cols = _profile_cols(profile, "domain_default_display_cols")
    if cols:
        return cols
    merged: list[str] = []
    for key in ("likely_category_columns", "likely_name_columns", "likely_amount_columns"):
        merged.extend(profile.get(key, []))
    return tuple(dict.fromkeys(merged))


def _top_n_extra_cols(profile: dict) -> tuple[str, ...]:
    return _profile_cols(profile, "domain_top_n_extra_cols")


def _column_label(col: str, profile: dict) -> str:
    labels = profile.get("domain_column_labels") or {}
    return labels.get(col, col)


def _internal_log_markers(profile: dict | None = None) -> tuple[str, ...]:
    markers = list(_INTERNAL_LOG_MARKERS)
    if profile:
        row_col = (profile.get("summary_row_config") or {}).get("row_type_column")
        if row_col:
            markers.append(f"{row_col}이")
    return tuple(markers)


def wants_full_detail(user_query: str) -> bool:
    return any(kw in user_query for kw in _FULL_DETAIL_KEYWORDS)


def _row_label(row: pd.Series, profile: dict) -> str:
    for col in profile.get("likely_name_columns", []):
        if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
            return str(row[col]).strip()
    for col in profile.get("likely_category_columns", []):
        if col in row.index and pd.notna(row[col]) and str(row[col]).strip():
            return str(row[col]).strip()
    return "해당 항목"


def _pick_existing_columns(df: pd.DataFrame | None, candidates: tuple[str, ...]) -> list[str]:
    if df is None or df.empty:
        return []
    return [c for c in candidates if c in df.columns]


def select_display_df(
    raw_df: pd.DataFrame | None,
    user_query: str,
    intent: dict,
    profile: dict,
    resolved_columns: dict | None = None,
) -> pd.DataFrame | None:
    """Return a slim DataFrame for UI display."""
    if raw_df is None or raw_df.empty:
        return raw_df
    if wants_full_detail(user_query):
        return raw_df.copy()

    resolved_columns = resolved_columns or {}
    operations = intent.get("operations") or []
    primary_op = _primary_operation(operations)

    if primary_op == "value_answer":
        primary_cols = _value_primary_cols(profile)
        secondary_cols = _value_secondary_cols(profile)
        cols = _pick_existing_columns(raw_df, primary_cols + secondary_cols)
        if not cols:
            cols = _pick_existing_columns(raw_df, _default_display_cols(profile))
        return raw_df[cols].head(1).copy() if cols else raw_df.head(1).copy()

    if primary_op == "top_n":
        criterion = resolved_columns.get(
            next((op.get("column", "") for op in operations if op.get("type") == "top_n"), ""),
            "",
        )
        name_cols = tuple(profile.get("domain_name_columns") or profile.get("likely_name_columns", [])[:2])
        cols = _pick_existing_columns(
            raw_df,
            (*name_cols, criterion, *_top_n_extra_cols(profile)),
        )
        cols = list(dict.fromkeys(c for c in cols if c))
        return raw_df[cols].copy() if cols else raw_df.copy()

    if primary_op in ("aggregate", "sort", "filter", "lookup"):
        cols = _pick_existing_columns(raw_df, _default_display_cols(profile))
        extra = [c for c in raw_df.columns if c not in cols][:4]
        cols = list(dict.fromkeys(cols + extra))
        return raw_df[cols].copy() if cols else raw_df.copy()

    cols = _pick_existing_columns(raw_df, _default_display_cols(profile))
    return raw_df[cols].copy() if cols else raw_df.copy()


def _primary_operation(operations: list[dict]) -> str | None:
    skip = {"filter_row_type", "exclude_summary"}
    for op in operations:
        if op.get("type") not in skip:
            return op.get("type")
    return operations[-1].get("type") if operations else None


def _format_amount_bullets(
    row: dict,
    columns: tuple[str, ...],
    profile: dict,
    *,
    skip_zero_secondary: bool = False,
) -> list[str]:
    secondary_cols = set(_value_secondary_cols(profile))
    bullets: list[str] = []
    for col in columns:
        if col not in row:
            continue
        val = row[col]
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        if skip_zero_secondary and col in secondary_cols and val == 0:
            continue
        if col in secondary_cols and val == 0:
            continue
        bullets.append(f"- {_column_label(col, profile)}: {_format_amount(val)}")
    return bullets


def _format_value_answer_message(metadata: dict, user_query: str, profile: dict) -> str:
    row = metadata.get("row") or {}
    label = metadata.get("label") or metadata.get("row_query", "해당 항목")
    lines = [f"**{label}** 항목을 찾았습니다.", ""]

    primary = _format_amount_bullets(row, _value_primary_cols(profile), profile)
    if primary:
        lines.extend(primary)
    else:
        lines.append("- 표시할 금액 정보가 없습니다.")

    secondary_parts = []
    for col in _value_secondary_cols(profile):
        if col not in row:
            continue
        val = row[col]
        if val is None or (isinstance(val, float) and pd.isna(val)) or val == 0:
            continue
        secondary_parts.append(f"{_column_label(col, profile)}은 {_format_amount(val)}")

    if secondary_parts:
        lines.extend(["", f"참고로 {', '.join(secondary_parts)}입니다."])

    if not wants_full_detail(user_query):
        lines.extend(["", "_더 많은 컬럼은 '전체 컬럼 보여줘'라고 요청하시면 표시합니다._"])

    return "\n".join(lines)


def _format_top_n_message(
    op: dict,
    df: pd.DataFrame,
    profile: dict,
    resolved: dict,
) -> str:
    user_col = op.get("column", "")
    resolved_col = resolved.get(user_col, user_col)
    row = df.iloc[0]
    label = _row_label(row, profile)
    val = row.get(resolved_col)
    direction = "낮은" if op.get("ascending") else "높은"
    n = op.get("n", 1)

    intro = ""
    if user_col and user_col != resolved_col:
        intro = f"'{user_col}'는 '{resolved_col}' 컬럼으로 해석했습니다.\n\n"

    if n > 1:
        body = f"{resolved_col}이(가) 가장 {direction} 항목 **{n}개**를 표시했습니다."
    else:
        body = (
            f"{resolved_col}이(가) 가장 {direction} 항목은 **{label}**이며, "
            f"금액은 {_format_amount(val)}입니다."
        )
    return intro + body


def _format_describe_message(df: pd.DataFrame, profile: dict) -> str:
    if profile.get("domain_describe_label"):
        name_cols = profile.get("domain_name_columns") or profile.get("likely_name_columns", [])
        amount_cols = profile.get("likely_amount_columns", [])
        key_cols = ", ".join(name_cols[:3]) if name_cols else "주요 식별 컬럼"
        amount_text = ", ".join(amount_cols[:5]) if amount_cols else "주요 금액 컬럼"
        examples = profile.get("domain_example_queries", [])[:3]
        example_lines = "\n".join(f'- "{q}"' for q in examples)
        return (
            f"이 파일은 **{profile['domain_describe_label']}** 형식의 예산·집행 데이터입니다 ({profile['rows']}행).\n\n"
            f"**주요 컬럼:** {key_cols}, {amount_text}\n\n"
            f"**질문 예시**\n{example_lines}"
        )

    info = describe_dataset_info(df, profile)
    lines = [
        f"이 데이터는 **{info['rows']}행**, **{info['columns']}열**입니다.",
        "",
        "**주요 식별 컬럼:** "
        + ", ".join(info["likely_category_columns"][:2] + info["likely_name_columns"][:2])
        or "없음",
    ]
    if info["likely_amount_columns"]:
        lines.append(
            "**주요 금액 컬럼:** " + ", ".join(info["likely_amount_columns"][:5])
        )
    if info["unnamed_columns"]:
        lines.append(f"\n_Unnamed 컬럼 {len(info['unnamed_columns'])}개는 정규화가 필요할 수 있습니다._")
    lines.extend(["", "**질문 예시**"])
    for ex in analysis_examples(profile)[:4]:
        lines.append(f"- {ex}")
    return "\n".join(lines)


def format_user_response(
    user_query: str,
    intent: dict,
    execution: dict,
    profile: dict,
) -> tuple[str, pd.DataFrame | None, pd.DataFrame | None]:
    """Build final message and display/raw DataFrames."""
    operations = intent.get("operations") or []
    resolved = execution.get("resolved_columns") or {}
    raw_df = execution.get("df")
    value_metadata = execution.get("value_metadata") or {}

    if operations and all(op.get("type") == "clarify" for op in operations):
        msg = execution.get("debug_logs", [UNKNOWN_MESSAGE])
        return (msg[0] if msg else UNKNOWN_MESSAGE), None, None

    if not operations and intent.get("message"):
        return intent["message"], raw_df, raw_df

    primary = _primary_operation(operations)
    message = ""

    if primary == "value_answer" and value_metadata:
        message = _format_value_answer_message(value_metadata, user_query, profile)
    elif primary == "top_n" and raw_df is not None and not raw_df.empty:
        top_op = next(op for op in operations if op.get("type") == "top_n")
        message = _format_top_n_message(top_op, raw_df, profile, resolved)
    elif primary == "describe_dataset":
        message = _format_describe_message(raw_df if raw_df is not None else pd.DataFrame(), profile)
    elif primary == "help":
        message = build_help_message(profile)
    elif primary == "aggregate" and raw_df is not None and not raw_df.empty:
        agg_op = next(op for op in operations if op.get("type") == "aggregate")
        agg_col = resolved.get(agg_op.get("agg_column", ""), agg_op.get("agg_column", ""))
        groups = [resolved.get(g, g) for g in agg_op.get("group_by", [])]
        message = f"{', '.join(groups)} 기준 {agg_col} {agg_op.get('agg_func', 'sum')} 결과입니다."
    elif primary == "sort" and raw_df is not None and not raw_df.empty:
        sort_op = next(op for op in operations if op.get("type") == "sort")
        col = resolved.get(sort_op.get("column", ""), sort_op.get("column", ""))
        direction = "오름차순" if sort_op.get("ascending", True) else "내림차순"
        message = f"{col} 기준 {direction} 정렬 결과입니다."
    elif primary == "filter" and raw_df is not None:
        message = (
            "조건에 맞는 행을 찾지 못했습니다."
            if raw_df.empty
            else f"조건에 맞는 {len(raw_df)}개 항목입니다."
        )
    elif primary == "filter_row_type" and raw_df is not None and not raw_df.empty:
        row_types = next(
            (op.get("row_types", []) for op in operations if op.get("type") == "filter_row_type"),
            [],
        )
        if row_types == ["합계"]:
            message = "전체 **합계** 행입니다."
        elif row_types == ["소계"]:
            category_cols = profile.get("likely_category_columns") or []
            cat_label = category_cols[0] if category_cols else "분류"
            message = f"{cat_label}별 **소계** 행입니다."
        else:
            message = f"요청하신 {len(raw_df)}개 항목입니다."

    analysis_types = {"top_n", "sort", "aggregate", "value_answer", "lookup", "filter"}
    had_analysis = any(op.get("type") in analysis_types for op in operations)
    if had_analysis and (raw_df is None or (isinstance(raw_df, pd.DataFrame) and raw_df.empty)):
        message = (
            "요청하신 조건에 맞는 데이터를 찾지 못했습니다. "
            "질문을 조금 더 구체적으로 바꿔 주세요."
        )

    if not message:
        if raw_df is not None and not raw_df.empty:
            message = f"요청을 처리했습니다. 결과 {len(raw_df)}행입니다."
        else:
            message = UNKNOWN_MESSAGE

    display_df = select_display_df(raw_df, user_query, intent, profile, resolved)
    if wants_full_detail(user_query):
        display_df = raw_df

    return message, display_df, raw_df


def is_internal_log(text: str, profile: dict | None = None) -> bool:
    return any(marker in text for marker in _internal_log_markers(profile))
