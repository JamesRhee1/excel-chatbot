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
    if op.get("_auto_selected_column"):
        body += f"\n정렬 기준: {resolved_col} (자동 선택)"
    return intro + body


def _derive_ranking_message(operations: list[dict], resolved: dict, *, primary: str) -> str | None:
    derive_op = next((op for op in operations if op.get("type") == "derive"), None)
    if not derive_op:
        return None
    rank_op = next((op for op in operations if op.get("type") == primary), None)
    if not rank_op:
        return None

    left = resolved.get(str(derive_op.get("left", "")), str(derive_op.get("left", "")))
    right_raw = derive_op.get("right", "")
    right = resolved.get(str(right_raw), str(right_raw))
    if derive_op.get("op") in {"divide", "percent"}:
        if primary == "top_n":
            n = rank_op.get("n", 1)
            return f"{left}/{right} 비율 기준 상위 {n}개입니다."
        direction = "오름차순" if rank_op.get("ascending", True) else "내림차순"
        return f"{left}/{right} 비율 기준 {direction} 정렬 결과입니다."

    new_col = derive_op.get("new_column", "파생 컬럼")
    if primary == "top_n":
        n = rank_op.get("n", 1)
        return f"{new_col} 기준 상위 {n}개입니다."
    direction = "오름차순" if rank_op.get("ascending", True) else "내림차순"
    return f"{new_col} 기준 {direction} 정렬 결과입니다."


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


_MULTI_OP_TYPES = frozenset({
    "combine_dataset",
    "summarize_by_file",
    "compare_item_across_files",
    "top_n_by_file",
    "top_n_overall",
    "multi_summary",
})


def _multi_display_cols(profile: dict) -> tuple[str, ...]:
    cols = profile.get("domain_multi_display_cols") or []
    if cols:
        return ("source_file", *cols)
    merged = ["source_file"]
    for key in ("likely_category_columns", "likely_name_columns", "likely_amount_columns"):
        merged.extend(profile.get(key, []))
    return tuple(dict.fromkeys(merged))


def _multi_hidden_cols(profile: dict) -> set[str]:
    hidden = {"source_sheet"}
    row_col = (profile.get("summary_row_config") or {}).get("row_type_column")
    if row_col:
        hidden.add(row_col)
    return hidden


def _pick_multi_display_columns(df: pd.DataFrame | None, profile: dict) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    hidden = _multi_hidden_cols(profile)
    cols = [c for c in _multi_display_cols(profile) if c in df.columns]
    extra = [c for c in df.columns if c not in cols and c not in hidden][:3]
    cols = list(dict.fromkeys(cols + extra))
    return df[cols].copy() if cols else df.copy()


def _compare_value_cols(profile: dict) -> tuple[str, ...]:
    return tuple(profile.get("domain_compare_columns") or profile.get("likely_amount_columns", []))


def _multi_row_summary(row: pd.Series, profile: dict) -> str:
    parts: list[str] = []
    for col in profile.get("likely_category_columns", []):
        if col in row.index and pd.notna(row[col]):
            parts.append(str(row[col]))
            break
    for col in profile.get("domain_name_columns") or profile.get("likely_name_columns", []):
        if col in row.index and pd.notna(row[col]):
            parts.append(str(row[col]))
            break
    for col in _compare_value_cols(profile):
        if col in row.index and pd.notna(row[col]):
            parts.append(_format_amount(row[col]))
            break
    return " / ".join(parts) if parts else "해당 항목"


def _format_multi_operation_message(
    operation: dict,
    result_df: pd.DataFrame | None,
    profile: dict,
    *,
    combined_df: pd.DataFrame | None = None,
    file_summary: dict | None = None,
) -> str:
    op_type = operation.get("type", "")
    if op_type == "combine_dataset":
        summary = file_summary or {}
        file_count = summary.get("file_count", 0)
        total_rows = summary.get("total_rows", len(combined_df) if combined_df is not None else 0)
        detail_rows = summary.get("detail_rows", 0)
        return (
            f"**{file_count}개** 파일을 통합했습니다.\n\n"
            f"- 통합 행 수: **{total_rows}행**\n"
            f"- 상세 행 수: **{detail_rows}행**\n"
            f"- 파일 구분 컬럼: `source_file`\n\n"
            "아래 표에서 통합 데이터 일부를 확인할 수 있습니다. "
            "전체 통합자료는 CSV 또는 Excel로 다운로드할 수 있습니다."
        )
    if op_type == "summarize_by_file" and result_df is not None and not result_df.empty:
        col = operation.get("value_column", "")
        sum_col = f"{col}_sum"
        lines = [f"파일별 **{col}** 합계를 비교했습니다.", ""]
        best_file = None
        best_val = None
        for _, row in result_df.iterrows():
            fname = row["source_file"]
            val = row.get(sum_col, row.get(col))
            lines.append(f"- **{fname}**: {_format_amount(val)}")
            if best_val is None or (pd.notna(val) and val > best_val):
                best_val = val
                best_file = fname
        if best_file:
            lines.extend(["", f"**{col}** 합계가 가장 큰 파일은 **{best_file}**입니다."])
        return "\n".join(lines)
    if op_type == "compare_item_across_files" and result_df is not None and not result_df.empty:
        item = operation.get("item_query", "")
        compare_cols = _compare_value_cols(profile)
        primary_col = compare_cols[0] if compare_cols else None
        lines = [f"파일별 **{item}** 항목을 비교했습니다.", ""]
        best_file = None
        best_primary = None
        for _, row in result_df.iterrows():
            fname = row["source_file"]
            detail_parts = []
            for col in compare_cols[:3]:
                val = row.get(col)
                if pd.notna(val):
                    label = (profile.get("domain_column_labels") or {}).get(col, col)
                    detail_parts.append(f"{label} {_format_amount(val)}")
            lines.append(f"- **{fname}**: {', '.join(detail_parts)}")
            if primary_col is not None:
                primary_val = row.get(primary_col)
                if primary_val is not None and pd.notna(primary_val):
                    if best_primary is None or primary_val > best_primary:
                        best_primary = primary_val
                        best_file = fname
        if best_file and primary_col:
            primary_label = (profile.get("domain_column_labels") or {}).get(primary_col, primary_col)
            lines.extend(["", f"**{item}** {primary_label}은 **{best_file}**가 가장 큽니다."])
        return "\n".join(lines)
    if op_type == "top_n_by_file" and result_df is not None and not result_df.empty:
        col = operation.get("value_column", "")
        lines = [f"각 파일별 **{col}** 최고 항목은 다음과 같습니다.", ""]
        for _, row in result_df.iterrows():
            lines.append(f"- **{row['source_file']}**: {_multi_row_summary(row, profile)}")
        return "\n".join(lines)
    if op_type == "top_n_overall" and result_df is not None and not result_df.empty:
        col = operation.get("value_column", "")
        n = operation.get("n", 5)
        lines = [f"전체 파일에서 **{col}** 상위 **{n}**개 항목입니다.", ""]
        for _, row in result_df.iterrows():
            lines.append(f"- **{row.get('source_file', '')}** / {_multi_row_summary(row, profile)}")
        return "\n".join(lines)
    if op_type == "multi_summary" and file_summary:
        return "\n".join([
            f"**{file_summary.get('file_count', 0)}개** 파일 요약입니다.",
            f"- 통합 행: **{file_summary.get('total_rows', 0)}**",
            f"- 상세 행: **{file_summary.get('detail_rows', 0)}**",
        ])
    if result_df is not None and not result_df.empty:
        return f"요청을 처리했습니다. 결과 {len(result_df)}행입니다."
    return "결과가 없습니다."


def format_user_response(
    user_query: str,
    intent: dict,
    execution: dict,
    profile: dict,
    *,
    combined_df: pd.DataFrame | None = None,
    file_summary: dict | None = None,
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
    if primary == "derive":
        if any(op.get("type") == "top_n" for op in operations):
            primary = "top_n"
        elif any(op.get("type") == "sort" for op in operations):
            primary = "sort"
    message = ""

    if primary in _MULTI_OP_TYPES:
        multi_op = next(op for op in operations if op.get("type") == primary)
        message = _format_multi_operation_message(
            multi_op,
            raw_df,
            profile,
            combined_df=combined_df,
            file_summary=file_summary,
        )
        display_df = _pick_multi_display_columns(raw_df, profile)
        if primary == "combine_dataset":
            preview = combined_df.head(20).copy() if combined_df is not None else None
            return message, _pick_multi_display_columns(preview, profile), combined_df
        return message, display_df, raw_df

    if primary == "value_answer" and value_metadata:
        message = _format_value_answer_message(value_metadata, user_query, profile)
    elif primary == "top_n" and raw_df is not None and not raw_df.empty:
        derive_message = _derive_ranking_message(operations, resolved, primary="top_n")
        if derive_message:
            message = derive_message
        else:
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
        derive_message = _derive_ranking_message(operations, resolved, primary="sort")
        if derive_message:
            message = derive_message
        else:
            sort_op = next(op for op in operations if op.get("type") == "sort")
            col = resolved.get(sort_op.get("column", ""), sort_op.get("column", ""))
            direction = "오름차순" if sort_op.get("ascending", True) else "내림차순"
            message = f"{col} 기준 {direction} 정렬 결과입니다."
            if sort_op.get("_auto_selected_column"):
                message += f"\n정렬 기준: {col} (자동 선택)"
    elif primary == "filter" and raw_df is not None:
        if raw_df.empty:
            filter_op = next((op for op in operations if op.get("type") == "filter"), {})
            col = resolved.get(filter_op.get("column", ""), filter_op.get("column", ""))
            op_sym = filter_op.get("op", "")
            value = filter_op.get("value", "")
            message = f"조건에 맞는 행이 0건입니다. (적용 조건: {col} {op_sym} {value})"
        else:
            message = f"조건에 맞는 {len(raw_df)}개 항목입니다."
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
        if primary != "filter":
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
        display_df = raw_df.copy() if raw_df is not None else None
    if isinstance(display_df, pd.DataFrame):
        display_df = display_df.reset_index(drop=True)

    return message, display_df, raw_df


def is_internal_log(text: str, profile: dict | None = None) -> bool:
    return any(marker in text for marker in _internal_log_markers(profile))
