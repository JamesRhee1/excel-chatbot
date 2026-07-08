"""Orchestrate load → profile → route/plan → execute → respond."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from agent.intent_utils import prepend_exclude_summary
from agent.response_formatter import format_user_response
from agent.router import route_query
from agent.tools import apply_operation
from core.dataset_builder import build_combined_dataset
from core.table_operations import build_multi_file_summary
from core.op_spec import OPERATION_SPEC_BY_TYPE, PipelineValidationError, validate_pipeline
from core.profiler import profile_dataframe
from core.reader import load_excel_with_domain
from core.workspace import LAST_RESULT_TABLE, Workspace
from core.writer import save_excel
from domains.registry import apply_derived_metrics
from llm.client import OllamaConnectionError, OllamaModelNotFoundError
from llm.intent import IntentParseError, parse_intent

DEFAULT_MAIN_TABLE = "main"
DEFAULT_COMBINED_TABLE = "combined"
_CONTEXT_SOURCE_HINTS = ("직전 결과에서", "여기서", "이 중에서")


def _apply_context_source(intent: dict, user_message: str) -> dict:
    if not any(hint in user_message for hint in _CONTEXT_SOURCE_HINTS):
        return intent
    intent = dict(intent)
    updated_ops: list[dict] = []
    for op in intent.get("operations") or []:
        new_op = dict(op)
        spec = OPERATION_SPEC_BY_TYPE.get(new_op.get("type", ""))
        if spec and spec.allows_source:
            new_op.setdefault("source", LAST_RESULT_TABLE)
        updated_ops.append(new_op)
    intent["operations"] = updated_ops
    return intent


def run(
    file_path: str | None = None,
    user_message: str = "",
    model: str | None = None,
    output_path: str | None = None,
    dry_run: bool = False,
    sheet_name: str | int = 0,
    file_results: list[dict] | None = None,
    workspace: Workspace | None = None,
) -> dict:
    profile: dict = {}
    ws = workspace or Workspace()
    default_table = DEFAULT_MAIN_TABLE
    combined_df: pd.DataFrame | None = None
    file_summary: dict | None = None

    try:
        if file_path:
            df, domain = load_excel_with_domain(file_path, sheet_name=sheet_name)
            ws.upsert_table(DEFAULT_MAIN_TABLE, df, source=file_path, domain=domain)
            default_table = DEFAULT_MAIN_TABLE
            profile = ws.get(DEFAULT_MAIN_TABLE).profile  # type: ignore[union-attr]

        elif file_results:
            combined_df = build_combined_dataset(file_results)
            combined_profile = profile_dataframe(combined_df)
            domain = combined_profile.get("domain", "generic")
            combined_df = apply_derived_metrics(combined_df, domain)
            combined_profile = profile_dataframe(combined_df, domain=domain)
            ws.upsert_table(
                DEFAULT_COMBINED_TABLE,
                combined_df,
                source="union",
                domain=domain,
                profile=combined_profile,
            )
            default_table = DEFAULT_COMBINED_TABLE
            profile = combined_profile
            file_summary = build_multi_file_summary(combined_df, profile=combined_profile)

        if not ws.list_tables():
            return _error_result("분석할 데이터가 없습니다.")

        if ws.get(LAST_RESULT_TABLE) and not file_path and not file_results:
            default_table = LAST_RESULT_TABLE
            last_table = ws.get(LAST_RESULT_TABLE)
            if last_table:
                profile = last_table.profile
        elif not profile:
            table = ws.get(default_table)
            profile = table.profile if table else {}
        elif ws.get(default_table) is None:
            table = ws.get(ws.list_tables()[0])
            default_table = table.name if table else default_table
            profile = table.profile if table else profile

        intent = route_query(user_message, profile)
        if intent is None:
            intent = parse_intent(user_message, profile, model=model)
        intent = prepend_exclude_summary(intent, user_message, profile)
        intent = _apply_context_source(intent, user_message)

        if dry_run:
            return _success_result(
                answer_type=intent.get("answer_type", "dataframe"),
                operations=intent["operations"],
                message=intent.get("message") or None,
                profile=_profile_summary(profile),
            )

        validate_pipeline(intent["operations"], ws)

        table = ws.get(default_table)
        context = {
            "combined_df": combined_df if combined_df is not None else (table.df if table else None),
            "file_summary": file_summary,
        }
        execution = _apply_operations_workspace(
            ws,
            intent["operations"],
            default_table=default_table,
            context=context,
        )

        if execution.get("df") is not None and isinstance(execution["df"], pd.DataFrame) and not execution["df"].empty:
            result_domain = profile.get("domain", "generic")
            ws.upsert_table(
                LAST_RESULT_TABLE,
                execution["df"],
                source="previous_turn",
                domain=result_domain,
                profile=profile_dataframe(execution["df"], domain=result_domain),
            )

        message, display_df, raw_df = format_user_response(
            user_message,
            intent,
            execution,
            profile,
            combined_df=context.get("combined_df"),
            file_summary=context.get("file_summary"),
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
            combined_df=context.get("combined_df"),
            operations=execution.get("applied", []),
            message=message,
            debug_logs=execution.get("debug_logs", []),
            profile=_profile_summary(profile),
            file_summary=context.get("file_summary"),
            saved_path=saved_path,
            backup_path=backup_path,
            workspace=ws,
        )

    except (IntentParseError, PipelineValidationError) as exc:
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


def _apply_operations_workspace(
    workspace: Workspace,
    operations: list[dict],
    *,
    default_table: str,
    context: dict,
) -> dict:
    current_df: pd.DataFrame | None = None
    current_profile: dict = {}
    debug_logs: list[str] = []
    resolved_columns: dict[str, str] = {}
    value_metadata: dict = {}
    applied: list[dict] = []
    produced_dataframe = False
    prev_output: str | None = None

    for index, operation in enumerate(operations):
        spec = OPERATION_SPEC_BY_TYPE[operation["type"]]
        source_name = operation.get("source")
        if source_name:
            table = workspace.get(source_name)
            if table is None:
                raise ValueError(f"테이블 '{source_name}'을(를) 찾을 수 없습니다.")
            current_df, current_profile = table.df, table.profile
        elif index == 0 or prev_output != "table" or current_df is None:
            table = workspace.get(default_table)
            if table is None:
                raise ValueError(f"기본 테이블 '{default_table}'이(가) 없습니다.")
            current_df, current_profile = table.df, table.profile
        if current_df is None:
            table = workspace.get(default_table)
            current_df = table.df if table else pd.DataFrame()
            current_profile = table.profile if table else {}

        try:
            outcome = apply_operation(
                current_df,
                operation,
                profile=current_profile,
                context=context,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(str(exc)) from exc

        resolved_columns.update(outcome.get("resolved_columns") or {})
        if outcome.get("value_metadata"):
            value_metadata = outcome["value_metadata"]
        if outcome.get("stats") and operation.get("type") == "multi_summary":
            context["file_summary"] = outcome["stats"]
        if outcome.get("df") is not None:
            current_df = outcome["df"]
            produced_dataframe = True
            save_as = operation.get("save_as")
            if save_as:
                saved_name = workspace.add_table(
                    save_as,
                    current_df,
                    source=f"op:{operation['type']}",
                    profile=current_profile,
                )
                debug_logs.append(f"결과를 '{saved_name}' 테이블로 저장했습니다.")
        if outcome.get("debug_log"):
            debug_logs.append(outcome["debug_log"])
        if outcome.get("message") and operation.get("type") == "clarify":
            debug_logs.append(outcome["message"])
        applied.append(operation)
        prev_output = spec.output_type

    clarify_only = operations and all(op.get("type") == "clarify" for op in operations)
    result_df = None if (not produced_dataframe and clarify_only) else current_df

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
    combined_df: pd.DataFrame | None = None,
    message: str | None = None,
    debug_logs: list[str] | None = None,
    profile: dict | None = None,
    file_summary: dict | None = None,
    saved_path: str | None = None,
    backup_path: str | None = None,
    workspace: Workspace | None = None,
) -> dict:
    return {
        "success": True,
        "answer_type": answer_type,
        "message": message,
        "df": df,
        "raw_df": raw_df,
        "combined_df": combined_df,
        "operations": operations,
        "debug_logs": debug_logs or [],
        "profile": profile,
        "file_summary": file_summary,
        "saved_path": saved_path,
        "backup_path": backup_path,
        "workspace": workspace,
        "error": None,
    }


def _error_result(error: str, operations: list[dict] | None = None) -> dict:
    return {
        "success": False,
        "answer_type": "message",
        "message": None,
        "df": None,
        "raw_df": None,
        "combined_df": None,
        "operations": operations or [],
        "debug_logs": [],
        "profile": None,
        "file_summary": None,
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
