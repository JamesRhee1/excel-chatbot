"""Orchestrate multi-file Excel analysis."""

from __future__ import annotations

import pandas as pd

from agent.multi_response_formatter import format_multi_response
from agent.multi_router import route_multi_query
from core.dataset_builder import build_combined_dataset
from core.multi_operations import (
    build_multi_file_summary,
    compare_item_across_files,
    summarize_by_file,
    top_n_by_file,
    top_n_overall,
)
from core.profiler import profile_dataframe
from domains.registry import apply_derived_metrics


def run_multi(
    file_results: list[dict],
    user_message: str,
    model: str | None = None,
) -> dict:
    """Run multi-file analysis pipeline (separate from single-file executor.run)."""
    debug_logs: list[str] = []
    try:
        combined_df = build_combined_dataset(file_results)
        combined_profile = profile_dataframe(combined_df)
        domain = combined_profile.get("domain", "generic")
        combined_df = apply_derived_metrics(combined_df, domain)
        combined_profile = profile_dataframe(combined_df, domain=domain)
        file_summary = build_multi_file_summary(combined_df, profile=combined_profile)

        intent = route_multi_query(user_message, combined_profile)
        if intent is None:
            examples = combined_profile.get("domain_multi_example_queries") or [
                "파일별 금액 합계 비교해줘",
                "항목을 파일별로 비교해줘",
            ]
            example_text = ", ".join(f"'{q}'" for q in examples[:2])
            return _error_result(f"다중 파일 질문을 이해하지 못했습니다. 예: {example_text}")

        operation = intent["operations"][0]
        op_type = operation["type"]
        result_df: pd.DataFrame | None = None

        if op_type == "combine_dataset":
            result_df = combined_df.head(50).copy()
            debug_logs.append(f"통합 완료: {len(combined_df)}행")

        elif op_type == "summarize_by_file":
            result_df = summarize_by_file(
                combined_df,
                operation["value_column"],
                profile=combined_profile,
            )
            debug_logs.append(f"summarize_by_file: {operation['value_column']}")

        elif op_type == "compare_item_across_files":
            result_df = compare_item_across_files(
                combined_df,
                operation["item_query"],
                value_columns=operation.get("value_columns"),
                profile=combined_profile,
            )
            if result_df.empty:
                return _error_result(f"'{operation['item_query']}' 항목을 파일별로 찾지 못했습니다.")
            debug_logs.append(f"compare_item: {operation['item_query']}")

        elif op_type == "top_n_by_file":
            result_df = top_n_by_file(
                combined_df,
                operation["value_column"],
                n=operation.get("n", 1),
                ascending=operation.get("ascending", False),
                profile=combined_profile,
            )
            debug_logs.append(f"top_n_by_file: {operation['value_column']}")

        elif op_type == "top_n_overall":
            result_df = top_n_overall(
                combined_df,
                operation["value_column"],
                n=operation.get("n", 5),
                ascending=operation.get("ascending", False),
                profile=combined_profile,
            )
            debug_logs.append(f"top_n_overall: {operation['value_column']}")

        elif op_type == "multi_summary":
            result_df = None
            debug_logs.append("multi_summary")

        elif op_type == "clarify":
            return _error_result(operation.get("message", "질문을 이해하지 못했습니다."))

        else:
            return _error_result(f"지원하지 않는 다중 파일 operation: {op_type}")

        message, display_df, raw_df = format_multi_response(
            user_message,
            intent,
            result_df,
            file_summary,
            combined_df,
            operation,
            profile=combined_profile,
        )

        answer_type = "mixed" if display_df is not None and message else "message"
        if display_df is None and message:
            answer_type = "message"

        return {
            "success": True,
            "answer_type": answer_type,
            "message": message,
            "df": display_df,
            "raw_df": raw_df,
            "combined_df": combined_df,
            "operations": intent["operations"],
            "debug_logs": debug_logs,
            "file_summary": file_summary,
            "error": None,
        }

    except ValueError as exc:
        return _error_result(str(exc))
    except KeyError as exc:
        return _error_result(f"컬럼을 찾을 수 없습니다: {exc}")
    except Exception as exc:
        return _error_result(f"다중 파일 처리 중 오류: {exc}")


def _error_result(error: str) -> dict:
    return {
        "success": False,
        "answer_type": "message",
        "message": None,
        "df": None,
        "raw_df": None,
        "combined_df": None,
        "operations": [],
        "debug_logs": [],
        "file_summary": None,
        "error": error,
    }
