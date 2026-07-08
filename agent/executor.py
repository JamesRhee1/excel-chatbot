"""Orchestrate load → profile → route/plan → execute → respond."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from agent.intent_utils import prepend_exclude_summary
from agent.response_formatter import format_user_response
from agent.router import route_query
from agent.tools import apply_operation
from core.profiler import profile_dataframe
from core.reader import load_excel_with_domain
from core.writer import save_excel
from llm.client import OllamaConnectionError, OllamaModelNotFoundError
from llm.intent import IntentParseError, parse_intent


def run(
    file_path: str,
    user_message: str,
    model: str | None = None,
    output_path: str | None = None,
    dry_run: bool = False,
    sheet_name: str | int = 0,
) -> dict:
    profile: dict = {}
    try:
        df, domain = load_excel_with_domain(file_path, sheet_name=sheet_name)
        profile = profile_dataframe(df, domain=domain)

        intent = route_query(user_message, profile)
        if intent is None:
            intent = parse_intent(user_message, profile, model=model)
        intent = prepend_exclude_summary(intent, user_message, profile)

        if dry_run:
            return _success_result(
                answer_type=intent.get("answer_type", "dataframe"),
                operations=intent["operations"],
                message=intent.get("message") or None,
                profile=_profile_summary(profile),
            )

        execution = _apply_operations(df, intent["operations"], profile)
        message, display_df, raw_df = format_user_response(
            user_message, intent, execution, profile
        )

        saved_path: str | None = None
        backup_path: str | None = None
        if output_path is not None and raw_df is not None:
            dest = Path(output_path)
            had_existing = dest.exists()
            saved_path = save_excel(raw_df, output_path, backup=True)
            if had_existing:
                backups = sorted(
                    dest.parent.glob(f"{dest.name}.bak_*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                backup_path = str(backups[0]) if backups else None

        answer_type = intent.get("answer_type", "dataframe")
        if display_df is not None and message:
            answer_type = "mixed"
        elif message and display_df is None:
            answer_type = "message"

        return _success_result(
            answer_type=answer_type,
            df=display_df,
            raw_df=raw_df,
            operations=execution.get("applied", []),
            message=message,
            debug_logs=execution.get("debug_logs", []),
            profile=_profile_summary(profile),
            saved_path=saved_path,
            backup_path=backup_path,
        )

    except IntentParseError as exc:
        return _error_result(str(exc))
    except OllamaConnectionError as exc:
        return _error_result(str(exc))
    except OllamaModelNotFoundError as exc:
        return _error_result(str(exc))
    except KeyError as exc:
        return _error_result(_missing_column_message(exc, profile))
    except ValueError as exc:
        return _error_result(_format_value_error(exc, profile))
    except Exception as exc:
        return _error_result(f"예상치 못한 오류가 발생했습니다: {exc}")


def _apply_operations(
    df: pd.DataFrame,
    operations: list[dict],
    profile: dict,
) -> dict:
    result_df: pd.DataFrame | None = df
    debug_logs: list[str] = []
    resolved_columns: dict[str, str] = {}
    value_metadata: dict = {}
    applied: list[dict] = []
    produced_dataframe = False

    for operation in operations:
        if result_df is None:
            result_df = df
        try:
            outcome = apply_operation(result_df, operation, profile=profile)
        except (KeyError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

        resolved_columns.update(outcome.get("resolved_columns") or {})
        if outcome.get("value_metadata"):
            value_metadata = outcome["value_metadata"]
        if outcome.get("df") is not None:
            result_df = outcome["df"]
            produced_dataframe = True
        if outcome.get("debug_log"):
            debug_logs.append(outcome["debug_log"])
        if outcome.get("message") and operation.get("type") == "clarify":
            debug_logs.append(outcome["message"])
        applied.append(operation)

    clarify_only = operations and all(op.get("type") == "clarify" for op in operations)
    if not produced_dataframe and clarify_only:
        result_df = None

    return {
        "df": result_df,
        "debug_logs": debug_logs,
        "resolved_columns": resolved_columns,
        "value_metadata": value_metadata,
        "applied": applied,
    }


def _profile_summary(profile: dict) -> dict:
    return {
        "rows": profile.get("rows"),
        "columns": profile.get("columns"),
        "likely_amount_columns": profile.get("likely_amount_columns", []),
        "likely_name_columns": profile.get("likely_name_columns", []),
        "likely_category_columns": profile.get("likely_category_columns", []),
    }


def _success_result(
    operations: list[dict],
    answer_type: str = "dataframe",
    df: pd.DataFrame | None = None,
    raw_df: pd.DataFrame | None = None,
    message: str | None = None,
    debug_logs: list[str] | None = None,
    profile: dict | None = None,
    saved_path: str | None = None,
    backup_path: str | None = None,
) -> dict:
    return {
        "success": True,
        "answer_type": answer_type,
        "message": message,
        "df": df,
        "raw_df": raw_df,
        "operations": operations,
        "debug_logs": debug_logs or [],
        "profile": profile,
        "saved_path": saved_path,
        "backup_path": backup_path,
        "error": None,
    }


def _error_result(error: str, operations: list[dict] | None = None) -> dict:
    return {
        "success": False,
        "answer_type": "message",
        "message": None,
        "df": None,
        "raw_df": None,
        "operations": operations or [],
        "debug_logs": [],
        "profile": None,
        "saved_path": None,
        "backup_path": None,
        "error": error,
    }


def _missing_column_message(exc: KeyError, profile: dict) -> str:
    key = exc.args[0] if exc.args else "?"
    missing = str(key).strip("'\"") if not isinstance(key, (list, tuple)) else ", ".join(map(str, key))
    cols = profile.get("column_names", [])
    return f"컬럼 '{missing}'을(를) 찾을 수 없어요. 있는 컬럼: {', '.join(cols[:8])}"


def _format_value_error(exc: ValueError, profile: dict) -> str:
    message = str(exc)
    if "찾지 못했습니다" in message or "찾을 수 없" in message:
        examples = profile.get("domain_example_queries") or [
            "가장 높은 행 찾아줘",
            "항목이 얼마야?",
        ]
        example_text = ", ".join(f"'{q}'" for q in examples[:2])
        return f"{message}\n\n다시 질문해보세요. 예: {example_text}"
    if "지원하지 않는 operation type" in message:
        return message
    return f"작업 실행 중 오류가 발생했습니다: {message}"
