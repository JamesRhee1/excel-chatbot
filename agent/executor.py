"""Orchestrate load → profile → route/plan → execute → respond."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from agent.intent_utils import prepend_exclude_summary
from agent.response_formatter import format_user_response
from agent.router import route_query
from agent.tools import apply_operation
from core.dataset_builder import build_combined_dataset
from core.table_operations import build_multi_file_summary
from core.op_spec import OPERATION_SPEC_BY_TYPE, PipelineValidationError, validate_pipeline
from core.profiler import is_id_like_column, profile_dataframe
from core.reader import load_excel_with_domain
from core.sandbox_runner import CODEGEN_WARNING, SandboxError, is_codegen_enabled, run_sandbox
from core.workspace import LAST_RESULT_TABLE, Workspace
from core.trace import TraceRecord, TraceWriter, new_trace_id, utc_timestamp
from core.verification import verify_operation
from core.writer import save_excel
from domains.registry import apply_derived_metrics
from llm.client import OllamaConnectionError, OllamaModelNotFoundError
from llm.intent import IntentParseError, parse_intent

DEFAULT_MAIN_TABLE = "main"
DEFAULT_COMBINED_TABLE = "combined"
_CONTEXT_SOURCE_HINTS = ("직전 결과에서", "여기서", "이 중에서")
_TRACE_WRITER = TraceWriter()


def _default_data_table(ws: Workspace) -> str:
    """Return the original uploaded/combined table, never last_result."""
    if ws.get(DEFAULT_COMBINED_TABLE):
        return DEFAULT_COMBINED_TABLE
    if ws.get(DEFAULT_MAIN_TABLE):
        return DEFAULT_MAIN_TABLE
    for name in ws.list_tables():
        if name != LAST_RESULT_TABLE:
            return name
    tables = ws.list_tables()
    return tables[0] if tables else DEFAULT_MAIN_TABLE


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


def _contains_column_hint(user_message: str, column: str) -> bool:
    msg = user_message.replace(" ", "")
    col = str(column).replace(" ", "")
    return bool(col) and col in msg


def _pick_auto_rank_column(df: pd.DataFrame, profile: dict, workspace: Workspace) -> str | None:
    last_ranked = workspace.get_state("last_ranked_column")
    if isinstance(last_ranked, str) and last_ranked in df.columns:
        return last_ranked

    likely_amount = profile.get("likely_amount_columns") or []
    if likely_amount:
        return likely_amount[0]

    for col in profile.get("numeric_columns") or []:
        if col in df.columns and not is_id_like_column(col):
            return str(col)
    return None


def _resolve_ranking_column(
    operation: dict,
    *,
    user_message: str,
    current_df: pd.DataFrame,
    profile: dict,
    workspace: Workspace,
) -> dict:
    op = dict(operation)
    raw_column = op.get("column")
    needs_auto = bool(op.get("_auto_selected_column"))
    if not needs_auto:
        needs_auto = not isinstance(raw_column, str) or not raw_column.strip()
    if not needs_auto and isinstance(raw_column, str):
        needs_auto = is_id_like_column(raw_column) and not _contains_column_hint(user_message, raw_column)

    if not needs_auto:
        return op

    selected = _pick_auto_rank_column(current_df, profile, workspace)
    if not selected:
        raise ValueError("정렬 기준 컬럼을 자동으로 선택할 수 없습니다. 기준 컬럼을 지정해 주세요.")
    op["column"] = selected
    op["_auto_selected_column"] = True
    return op


def _resolve_llm_profile(
    *,
    user_message: str,
    workspace: Workspace,
    default_table: str,
    fallback_profile: dict,
) -> tuple[str, dict]:
    source_name = LAST_RESULT_TABLE if any(hint in user_message for hint in _CONTEXT_SOURCE_HINTS) else default_table
    source_table = workspace.get(source_name) or workspace.get(default_table)
    if source_table is None or source_table.df is None:
        return default_table, fallback_profile
    refreshed = profile_dataframe(source_table.df, domain=source_table.domain)
    return source_table.name, refreshed


def _prepare_operations_for_execution(
    operations: list[dict],
    *,
    user_message: str,
    workspace: Workspace,
    default_table: str,
) -> list[dict]:
    prepared: list[dict] = []
    for operation in operations:
        op = dict(operation)
        if op.get("type") in {"top_n", "sort"}:
            source_name = op.get("source") or default_table
            source_table = workspace.get(source_name)
            if source_table is not None:
                op = _resolve_ranking_column(
                    op,
                    user_message=user_message,
                    current_df=source_table.df,
                    profile=source_table.profile,
                    workspace=workspace,
                )
        prepared.append(op)
    return prepared


def _emit_run_trace(
    *,
    trace_id: str,
    started: float,
    user_message: str,
    route_path: str,
    intent: dict,
    operations_applied: list[dict],
    per_op_ms: list[float],
    verification_summaries: list[str],
    answer_type: str,
    error: str | None,
    input_rows: int | None,
    input_columns: list[str],
    output_rows: int | None,
    output_columns: list[str],
) -> None:
    total_ms = (time.perf_counter() - started) * 1000
    _TRACE_WRITER.write(
        TraceRecord(
            trace_id=trace_id,
            timestamp=utc_timestamp(),
            user_message=user_message,
            route_path=route_path,
            intent=intent,
            operations_applied=operations_applied,
            per_op_ms=per_op_ms,
            verification_summaries=verification_summaries,
            answer_type=answer_type,
            error=error,
            total_ms=total_ms,
            input_rows=input_rows,
            input_columns=input_columns,
            output_rows=output_rows,
            output_columns=output_columns,
        )
    )


def _attach_trace_id(result: dict, trace_id: str, *, route_path: str | None = None) -> dict:
    result["trace_id"] = trace_id
    if route_path is not None:
        result["route_path"] = route_path
    return result


def _is_clarify_only(intent: dict) -> bool:
    operations = intent.get("operations") or []
    return bool(operations) and all(op.get("type") == "clarify" for op in operations)


def _codegen_pending_result(
    code: str,
    *,
    workspace: Workspace,
    profile: dict,
    user_message: str,
) -> dict:
    return {
        "success": True,
        "answer_type": "codegen_pending",
        "message": (
            "표준 연산으로 처리할 수 없어 pandas 코드를 생성했습니다. "
            "코드를 검토한 뒤 [실행] 또는 [취소]를 선택하세요."
        ),
        "df": None,
        "raw_df": None,
        "combined_df": None,
        "operations": [{"type": "codegen_proposal"}],
        "debug_logs": [],
        "profile": _profile_summary(profile),
        "file_summary": None,
        "saved_path": None,
        "backup_path": None,
        "workspace": workspace,
        "verification": [],
        "codegen_pending": True,
        "generated_code": code,
        "codegen_user_message": user_message,
        "error": None,
    }


def run(
    file_path: str | None = None,
    user_message: str = "",
    model: str | None = None,
    output_path: str | None = None,
    dry_run: bool = False,
    sheet_name: str | int = 0,
    file_results: list[dict] | None = None,
    workspace: Workspace | None = None,
    approved_codegen_code: str | None = None,
) -> dict:
    trace_id = new_trace_id()
    started = time.perf_counter()
    route_path = "rule"
    intent: dict = {}
    operations_applied: list[dict] = []
    per_op_ms: list[float] = []
    verification_summaries: list[str] = []
    answer_type = "message"
    input_rows: int | None = None
    input_columns: list[str] = []
    output_rows: int | None = None
    output_columns: list[str] = []
    result: dict | None = None

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
            result = _error_result("분석할 데이터가 없습니다.")
        else:
            if not file_path and not file_results:
                default_table = _default_data_table(ws)
                table = ws.get(default_table)
                if table:
                    profile = table.profile
            elif not profile:
                table = ws.get(default_table)
                profile = table.profile if table else {}
            elif ws.get(default_table) is None:
                table = ws.get(ws.list_tables()[0])
                default_table = table.name if table else default_table
                profile = table.profile if table else profile

            intent = route_query(user_message, profile) or {}
            route_path = "rule" if intent else "llm"
            if approved_codegen_code:
                pass
            elif not intent:
                llm_source_name, llm_profile = _resolve_llm_profile(
                    user_message=user_message,
                    workspace=ws,
                    default_table=default_table,
                    fallback_profile=profile,
                )
                if any(hint in user_message for hint in _CONTEXT_SOURCE_HINTS):
                    default_table = llm_source_name
                profile = llm_profile
                intent = parse_intent(user_message, llm_profile, model=model)
            if not approved_codegen_code:
                intent = prepend_exclude_summary(intent, user_message, profile)
                intent = _apply_context_source(intent, user_message)
                intent["operations"] = _prepare_operations_for_execution(
                    intent.get("operations") or [],
                    user_message=user_message,
                    workspace=ws,
                    default_table=default_table,
                )

            table = ws.get(default_table)
            if table and table.df is not None:
                input_rows = len(table.df)
                input_columns = list(table.df.columns.astype(str))

            if approved_codegen_code:
                if not is_codegen_enabled():
                    result = _error_result("코드 실행은 EXCEL_CHATBOT_ENABLE_CODEGEN=1 일 때만 허용됩니다.")
                elif table is None or table.df is None:
                    result = _error_result("코드 실행에 사용할 데이터가 없습니다.")
                else:
                    route_path = "codegen"
                    operations_applied = [{"type": "codegen"}]
                    try:
                        output_df = run_sandbox(approved_codegen_code, table.df)
                    except SandboxError as exc:
                        result = _error_result(str(exc))
                    else:
                        result_domain = profile.get("domain", "generic")
                        ws.upsert_table(
                            LAST_RESULT_TABLE,
                            output_df,
                            source="codegen",
                            domain=result_domain,
                            profile=profile_dataframe(output_df, domain=result_domain),
                        )
                        output_rows = len(output_df)
                        output_columns = list(output_df.columns.astype(str))
                        message = f"{CODEGEN_WARNING}\n\n코드 실행이 완료되었습니다. ({len(output_df)}행)"
                        result = _success_result(
                            answer_type="dataframe",
                            df=output_df,
                            raw_df=output_df,
                            operations=operations_applied,
                            message=message,
                            profile=_profile_summary(profile),
                            workspace=ws,
                            verification=[],
                        )
                        intent = {
                            "answer_type": "dataframe",
                            "operations": operations_applied,
                            "codegen": True,
                        }
            elif dry_run:
                operations_applied = list(intent.get("operations") or [])
                answer_type = intent.get("answer_type", "dataframe")
                result = _success_result(
                    answer_type=answer_type,
                    operations=operations_applied,
                    message=intent.get("message") or None,
                    profile=_profile_summary(profile),
                )
            elif (
                is_codegen_enabled()
                and _is_clarify_only(intent)
            ):
                from llm.codegen import generate_pandas_code

                generated_code = generate_pandas_code(user_message, profile, model=model)
                if generated_code:
                    route_path = "llm"
                    operations_applied = [{"type": "codegen_proposal"}]
                    intent = {
                        "answer_type": "codegen_pending",
                        "operations": operations_applied,
                        "codegen_proposal": True,
                    }
                    result = _codegen_pending_result(
                        generated_code,
                        workspace=ws,
                        profile=profile,
                        user_message=user_message,
                    )
                else:
                    validate_pipeline(intent["operations"], ws)
                    context = {
                        "combined_df": combined_df if combined_df is not None else (table.df if table else None),
                        "file_summary": file_summary,
                    }
                    execution = _apply_operations_workspace(
                        ws,
                        intent["operations"],
                        user_message=user_message,
                        default_table=default_table,
                        context=context,
                    )
                    operations_applied = execution.get("applied", [])
                    per_op_ms = execution.get("per_op_ms", [])
                    verification_summaries = [
                        report["summary"] for report in execution.get("verification", [])
                    ]
                    ranked_column = execution.get("last_ranked_column")
                    if isinstance(ranked_column, str) and ranked_column:
                        ws.set_state("last_ranked_column", ranked_column)
                    route_path = "llm_fallback_clarify"
                    message, display_df, raw_df = format_user_response(
                        user_message,
                        intent,
                        execution,
                        profile,
                        combined_df=context.get("combined_df"),
                        file_summary=context.get("file_summary"),
                    )
                    answer_type = "message"
                    result = _success_result(
                        answer_type=answer_type,
                        df=display_df,
                        raw_df=raw_df,
                        operations=operations_applied,
                        message=message,
                        debug_logs=execution.get("debug_logs", []),
                        profile=_profile_summary(profile),
                        workspace=ws,
                        verification=execution.get("verification", []),
                    )
            else:
                validate_pipeline(intent["operations"], ws)

                context = {
                    "combined_df": combined_df if combined_df is not None else (table.df if table else None),
                    "file_summary": file_summary,
                }
                execution = _apply_operations_workspace(
                    ws,
                    intent["operations"],
                    user_message=user_message,
                    default_table=default_table,
                    context=context,
                )
                operations_applied = execution.get("applied", [])
                per_op_ms = execution.get("per_op_ms", [])
                verification_summaries = [
                    report["summary"] for report in execution.get("verification", [])
                ]

                if route_path == "llm" and operations_applied and all(
                    op.get("type") == "clarify" for op in operations_applied
                ):
                    route_path = "llm_fallback_clarify"

                if execution.get("df") is not None and isinstance(execution["df"], pd.DataFrame) and not execution["df"].empty:
                    result_domain = profile.get("domain", "generic")
                    ws.upsert_table(
                        LAST_RESULT_TABLE,
                        execution["df"],
                        source="previous_turn",
                        domain=result_domain,
                        profile=profile_dataframe(execution["df"], domain=result_domain),
                    )
                ranked_column = execution.get("last_ranked_column")
                if isinstance(ranked_column, str) and ranked_column:
                    ws.set_state("last_ranked_column", ranked_column)

                message, display_df, raw_df = format_user_response(
                    user_message,
                    intent,
                    execution,
                    profile,
                    combined_df=context.get("combined_df"),
                    file_summary=context.get("file_summary"),
                )

                verification_reports = execution.get("verification", [])
                failed_summaries = [
                    report["summary"] for report in verification_reports if not report.get("passed")
                ]
                if failed_summaries:
                    warning_block = "\n".join(f"⚠ 검증 경고: {summary}" for summary in failed_summaries)
                    message = f"{warning_block}\n\n{message}" if message else warning_block

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

                result_df = raw_df if raw_df is not None else execution.get("df")
                if isinstance(result_df, pd.DataFrame):
                    output_rows = len(result_df)
                    output_columns = list(result_df.columns.astype(str))

                result = _success_result(
                    answer_type=answer_type,
                    df=display_df,
                    raw_df=raw_df,
                    combined_df=context.get("combined_df"),
                    operations=operations_applied,
                    message=message,
                    debug_logs=execution.get("debug_logs", []),
                    profile=_profile_summary(profile),
                    file_summary=context.get("file_summary"),
                    saved_path=saved_path,
                    backup_path=backup_path,
                    workspace=ws,
                    verification=verification_reports,
                )

    except (IntentParseError, PipelineValidationError) as exc:
        result = _error_result(str(exc))
    except OllamaConnectionError as exc:
        result = _error_result(str(exc))
    except OllamaModelNotFoundError as exc:
        result = _error_result(str(exc))
    except KeyError as exc:
        result = _error_result(_missing_column_message(exc, profile))
    except ValueError as exc:
        result = _error_result(_format_value_error(exc, profile))
    except Exception as exc:
        result = _error_result(f"예상치 못한 오류가 발생했습니다: {exc}")

    if result is None:
        result = _error_result("알 수 없는 오류가 발생했습니다.")

    _emit_run_trace(
        trace_id=trace_id,
        started=started,
        user_message=user_message,
        route_path=route_path,
        intent=intent,
        operations_applied=operations_applied,
        per_op_ms=per_op_ms,
        verification_summaries=verification_summaries,
        answer_type=result.get("answer_type", answer_type),
        error=result.get("error"),
        input_rows=input_rows,
        input_columns=input_columns,
        output_rows=output_rows,
        output_columns=output_columns,
    )
    return _attach_trace_id(result, trace_id, route_path=route_path)


def _apply_operations_workspace(
    workspace: Workspace,
    operations: list[dict],
    *,
    user_message: str,
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
    verification: list[dict] = []
    per_op_ms: list[float] = []
    last_ranked_column: str | None = None

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

        operation_to_apply = dict(operation)
        if operation_to_apply.get("type") in {"top_n", "sort"}:
            operation_to_apply = _resolve_ranking_column(
                operation_to_apply,
                user_message=user_message,
                current_df=current_df,
                profile=current_profile,
                workspace=workspace,
            )

        input_df = current_df.copy()

        op_started = time.perf_counter()
        try:
            outcome = apply_operation(
                current_df,
                operation_to_apply,
                profile=current_profile,
                context=context,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        per_op_ms.append((time.perf_counter() - op_started) * 1000)

        resolved_columns.update(outcome.get("resolved_columns") or {})
        if outcome.get("value_metadata"):
            value_metadata = outcome["value_metadata"]
        if outcome.get("stats") and operation_to_apply.get("type") == "multi_summary":
            context["file_summary"] = outcome["stats"]
        if outcome.get("df") is not None:
            verify_args = dict(operation_to_apply)
            if operation_to_apply.get("type") == "exclude_summary":
                verify_args["_profile"] = current_profile
            report = verify_operation(
                operation_to_apply["type"],
                input_df,
                outcome["df"],
                verify_args,
            )
            verification.append(report.to_dict())
            current_df = outcome["df"]
            produced_dataframe = True
            save_as = operation_to_apply.get("save_as")
            if save_as:
                saved_name = workspace.add_table(
                    save_as,
                    current_df,
                    source=f"op:{operation_to_apply['type']}",
                    profile=current_profile,
                )
                debug_logs.append(f"결과를 '{saved_name}' 테이블로 저장했습니다.")
        if outcome.get("debug_log"):
            debug_logs.append(outcome["debug_log"])
        if outcome.get("message") and operation_to_apply.get("type") == "clarify":
            debug_logs.append(outcome["message"])
        if operation_to_apply.get("type") in {"top_n", "sort"}:
            last_ranked_column = str(operation_to_apply.get("column", "")).strip() or last_ranked_column
        applied.append(operation_to_apply)
        prev_output = spec.output_type

    clarify_only = operations and all(op.get("type") == "clarify" for op in operations)
    result_df = None if (not produced_dataframe and clarify_only) else current_df

    return {
        "df": result_df,
        "debug_logs": debug_logs,
        "resolved_columns": resolved_columns,
        "value_metadata": value_metadata,
        "applied": applied,
        "verification": verification,
        "per_op_ms": per_op_ms,
        "last_ranked_column": last_ranked_column,
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
    verification: list[dict] | None = None,
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
        "verification": verification or [],
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
    if "수식은 컬럼명으로" in message:
        return message
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
