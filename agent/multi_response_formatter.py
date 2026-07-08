"""User-facing response formatting for multi-file analysis."""

from __future__ import annotations

import pandas as pd

from core.operations import _format_amount


def _display_cols(profile: dict) -> tuple[str, ...]:
    cols = profile.get("domain_multi_display_cols") or []
    if cols:
        return ("source_file", *cols)
    merged = ["source_file"]
    for key in ("likely_category_columns", "likely_name_columns", "likely_amount_columns"):
        merged.extend(profile.get(key, []))
    return tuple(dict.fromkeys(merged))


def _hidden_cols(profile: dict) -> set[str]:
    hidden = {"source_sheet"}
    row_col = (profile.get("summary_row_config") or {}).get("row_type_column")
    if row_col:
        hidden.add(row_col)
    return hidden


def _pick_display_columns(df: pd.DataFrame | None, profile: dict) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    hidden = _hidden_cols(profile)
    cols = [c for c in _display_cols(profile) if c in df.columns]
    extra = [c for c in df.columns if c not in cols and c not in hidden][:3]
    cols = list(dict.fromkeys(cols + extra))
    return df[cols].copy() if cols else df.copy()


def _compare_value_cols(profile: dict) -> tuple[str, ...]:
    return tuple(profile.get("domain_compare_columns") or profile.get("likely_amount_columns", []))


def _row_summary(row: pd.Series, profile: dict) -> str:
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


def format_multi_response(
    user_query: str,
    intent: dict,
    result_df: pd.DataFrame | None,
    file_summary: dict | None,
    combined_df: pd.DataFrame | None,
    operation: dict,
    profile: dict | None = None,
) -> tuple[str, pd.DataFrame | None, pd.DataFrame | None]:
    """Return (message, display_df, raw_df)."""
    profile = profile or {}
    op_type = operation.get("type", "")
    raw_df = result_df
    display_df = _pick_display_columns(result_df, profile)

    if op_type == "combine_dataset":
        summary = file_summary or {}
        file_count = summary.get("file_count", 0)
        total_rows = summary.get("total_rows", len(combined_df) if combined_df is not None else 0)
        detail_rows = summary.get("detail_rows", 0)
        message = (
            f"**{file_count}개** 파일을 통합했습니다.\n\n"
            f"- 통합 행 수: **{total_rows}행**\n"
            f"- 상세 행 수: **{detail_rows}행**\n"
            f"- 파일 구분 컬럼: `source_file`\n\n"
            "아래 표에서 통합 데이터 일부를 확인할 수 있습니다. "
            "전체 통합자료는 CSV 또는 Excel로 다운로드할 수 있습니다."
        )
        preview = combined_df.head(20).copy() if combined_df is not None else None
        return message, _pick_display_columns(preview, profile), combined_df

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
        return "\n".join(lines), display_df, raw_df

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
        return "\n".join(lines), display_df, raw_df

    if op_type == "top_n_by_file" and result_df is not None and not result_df.empty:
        col = operation.get("value_column", "")
        lines = [f"각 파일별 **{col}** 최고 항목은 다음과 같습니다.", ""]
        for _, row in result_df.iterrows():
            fname = row["source_file"]
            summary = _row_summary(row, profile)
            lines.append(f"- **{fname}**: {summary}")
        return "\n".join(lines), display_df, raw_df

    if op_type == "top_n_overall" and result_df is not None and not result_df.empty:
        col = operation.get("value_column", "")
        n = operation.get("n", 5)
        lines = [f"전체 파일에서 **{col}** 상위 **{n}**개 항목입니다.", ""]
        for _, row in result_df.iterrows():
            fname = row.get("source_file", "")
            summary = _row_summary(row, profile)
            lines.append(f"- **{fname}** / {summary}")
        return "\n".join(lines), display_df, raw_df

    if op_type == "multi_summary" and file_summary:
        lines = [
            f"**{file_summary.get('file_count', 0)}개** 파일 요약입니다.",
            f"- 통합 행: **{file_summary.get('total_rows', 0)}**",
            f"- 상세 행: **{file_summary.get('detail_rows', 0)}**",
        ]
        return "\n".join(lines), display_df, raw_df

    if result_df is not None and not result_df.empty:
        return f"요청을 처리했습니다. 결과 {len(result_df)}행입니다.", display_df, raw_df

    return "결과가 없습니다.", display_df, raw_df
