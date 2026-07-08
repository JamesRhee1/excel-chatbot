"""Load multiple Excel files for combined analysis."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from core.reader import list_sheets, load_excel_with_domain
from core.workspace import Workspace


def _resolve_file_name(item: Any) -> str:
    if isinstance(item, (str, Path)):
        return Path(item).name
    name = getattr(item, "name", None)
    if name:
        return str(name)
    return "unknown.xlsx"


def _resolve_sheet_name(path: str, sheet_name: str | int) -> str:
    if isinstance(sheet_name, str):
        return sheet_name
    try:
        sheets = list_sheets(path)
        if sheets and 0 <= int(sheet_name) < len(sheets):
            return sheets[int(sheet_name)]
    except Exception:
        pass
    return str(sheet_name)


def _materialize_upload(item: Any) -> tuple[str, bool]:
    """Return (path, is_temp) for a path string or uploaded file-like object."""
    if isinstance(item, (str, Path)):
        return str(item), False

    getvalue = getattr(item, "getvalue", None)
    read = getattr(item, "read", None)
    if getvalue is None and read is None:
        raise ValueError(f"지원하지 않는 업로드 타입: {type(item)!r}")

    suffix = Path(_resolve_file_name(item)).suffix or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="multi_upload_")
    data = getvalue() if getvalue else read()
    tmp.write(data)
    tmp.close()
    return tmp.name, True


def _table_name_from_file(file_name: str) -> str:
    stem = Path(file_name).stem
    return stem or file_name


def load_into_workspace(
    workspace: Workspace,
    uploaded_files: list[Any],
    sheet_name: str | int = 0,
) -> list[dict]:
    """Load files into workspace tables; return per-file load results."""
    results: list[dict] = []

    for item in uploaded_files or []:
        file_name = _resolve_file_name(item)
        temp_path: str | None = None
        try:
            path, is_temp = _materialize_upload(item)
            if is_temp:
                temp_path = path

            raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
            normalized_df, domain = load_excel_with_domain(path, sheet_name=sheet_name)
            resolved_sheet = _resolve_sheet_name(path, sheet_name)
            source = f"{file_name}/{resolved_sheet}"
            table_name = workspace.add_table(
                _table_name_from_file(file_name),
                normalized_df,
                source,
                domain=domain,
            )
            table = workspace.get(table_name)
            assert table is not None

            results.append(
                {
                    "file_name": file_name,
                    "sheet_name": resolved_sheet,
                    "table_name": table_name,
                    "success": True,
                    "raw_df": raw,
                    "normalized_df": normalized_df,
                    "profile": table.profile,
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "file_name": file_name,
                    "sheet_name": str(sheet_name),
                    "table_name": None,
                    "success": False,
                    "raw_df": None,
                    "normalized_df": None,
                    "profile": None,
                    "error": str(exc),
                }
            )
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

    return results


def load_multiple_excels(
    uploaded_files: list[Any],
    sheet_name: str | int = 0,
) -> list[dict]:
    """Load and profile multiple Excel files; failures are recorded per file."""
    workspace = Workspace()
    return load_into_workspace(workspace, uploaded_files, sheet_name=sheet_name)
