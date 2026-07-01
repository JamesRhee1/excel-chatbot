"""Orchestrate load → intent parse → operation chain."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from agent.tools import apply_operation
from core.reader import load_excel, summarize
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
    """Execute a natural-language request against an Excel file.

    Flow: load_excel → summarize → parse_intent → chain apply_operation → optional save.

    Args:
        file_path: Path to the Excel file.
        user_message: Natural-language request from the user.
        model: Ollama model name (None uses OLLAMA_MODEL env default).
        output_path: If set, save the result DataFrame via core.writer.save_excel.
        dry_run: If True, parse intent only without executing or saving.
        sheet_name: Sheet name or index to load.

    Returns:
        Structured result dict with success, df, operations, paths, and error fields.
    """
    columns: list[str] = []
    try:
        df = load_excel(file_path, sheet_name=sheet_name)
        summary = summarize(df)
        columns = summary["column_names"]
        intent = parse_intent(user_message, columns, model=model)

        if dry_run:
            return _success_result(operations=intent["operations"])

        result_df, applied = _apply_operations(df, intent["operations"])
        saved_path: str | None = None
        backup_path: str | None = None

        if output_path is not None:
            dest = Path(output_path)
            had_existing = dest.exists()
            saved_path = save_excel(result_df, output_path, backup=True)
            if had_existing:
                backups = sorted(
                    dest.parent.glob(f"{dest.name}.bak_*"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                backup_path = str(backups[0]) if backups else None

        return _success_result(
            df=result_df,
            operations=applied,
            saved_path=saved_path,
            backup_path=backup_path,
        )

    except IntentParseError as exc:
        return _error_result(
            f"요청을 이해하지 못했어요. 다시 말씀해 주세요. ({exc})"
        )
    except OllamaConnectionError as exc:
        return _error_result(str(exc))
    except OllamaModelNotFoundError as exc:
        return _error_result(str(exc))
    except KeyError as exc:
        return _error_result(_missing_column_message(exc, columns))
    except ValueError as exc:
        return _error_result(_format_value_error(exc))
    except Exception as exc:
        return _error_result(f"예상치 못한 오류가 발생했습니다: {exc}")


def _apply_operations(
    df: pd.DataFrame,
    operations: list[dict],
) -> tuple[pd.DataFrame, list[dict]]:
    """Apply operations sequentially, returning the result and applied log."""
    result_df = df
    applied: list[dict] = []
    for operation in operations:
        result_df = apply_operation(result_df, operation)
        applied.append(operation)
    return result_df, applied


def _success_result(
    operations: list[dict],
    df: pd.DataFrame | None = None,
    saved_path: str | None = None,
    backup_path: str | None = None,
) -> dict:
    return {
        "success": True,
        "df": df,
        "operations": operations,
        "saved_path": saved_path,
        "backup_path": backup_path,
        "error": None,
    }


def _error_result(error: str, operations: list[dict] | None = None) -> dict:
    return {
        "success": False,
        "df": None,
        "operations": operations or [],
        "saved_path": None,
        "backup_path": None,
        "error": error,
    }


def _missing_column_message(exc: KeyError, columns: list[str]) -> str:
    key = exc.args[0] if exc.args else "?"
    if isinstance(key, (list, tuple)):
        missing = ", ".join(str(item) for item in key)
    else:
        missing = str(key).strip("'\"")
    available = ", ".join(columns)
    return f"컬럼 '{missing}'을(를) 찾을 수 없어요. 있는 컬럼: {available}"


def _format_value_error(exc: ValueError) -> str:
    message = str(exc)
    if "지원하지 않는 operation type" in message:
        return message
    if "Unsupported operator" in message:
        return (
            "지원하지 않는 필터 연산자입니다. "
            "사용 가능: >, <, >=, <=, ==, !=, contains"
        )
    if "Unsupported agg_func" in message:
        return (
            "지원하지 않는 집계 함수입니다. "
            "사용 가능: sum, mean, count, max, min"
        )
    return f"작업 실행 중 오류가 발생했습니다: {message}"
