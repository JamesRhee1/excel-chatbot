"""Tests for pipeline validation against workspace."""

from __future__ import annotations

import pandas as pd
import pytest

from core.op_spec import PipelineValidationError, validate_pipeline
from core.workspace import Workspace


@pytest.fixture
def workspace_with_main() -> Workspace:
    ws = Workspace()
    ws.add_table("main", pd.DataFrame({"a": [1, 2], "b": [3, 4]}), source="main.xlsx")
    return ws


def test_validate_pipeline_missing_source_table(workspace_with_main: Workspace) -> None:
    operations = [{"type": "filter", "source": "missing", "column": "a", "op": ">", "value": 0}]
    with pytest.raises(PipelineValidationError, match="missing"):
        validate_pipeline(operations, workspace_with_main)


def test_validate_pipeline_type_mismatch_after_scalar(workspace_with_main: Workspace) -> None:
    operations = [
        {"type": "summary_stats", "column": "a"},
        {"type": "top_n", "column": "b", "n": 1, "ascending": False},
    ]
    with pytest.raises(PipelineValidationError, match="테이블이 아니라"):
        validate_pipeline(operations, workspace_with_main)


def test_validate_pipeline_rejects_source_on_help(workspace_with_main: Workspace) -> None:
    operations = [{"type": "help", "source": "main"}]
    with pytest.raises(PipelineValidationError, match="source를 지정할 수 없습니다"):
        validate_pipeline(operations, workspace_with_main)


def test_validate_pipeline_save_as_on_scalar_rejected(workspace_with_main: Workspace) -> None:
    operations = [{"type": "summary_stats", "column": "a", "save_as": "stats"}]
    with pytest.raises(PipelineValidationError, match="save_as"):
        validate_pipeline(operations, workspace_with_main)


def test_validate_pipeline_valid_chain_with_save_as(workspace_with_main: Workspace) -> None:
    operations = [
        {
            "type": "filter",
            "source": "main",
            "column": "a",
            "op": ">",
            "value": 0,
            "save_as": "filtered",
        },
        {"type": "top_n", "column": "b", "n": 1, "ascending": False},
    ]
    validate_pipeline(operations, workspace_with_main)


def test_validate_pipeline_empty_workspace(workspace_with_main: Workspace) -> None:
    ws = Workspace()
    operations = [{"type": "top_n", "column": "a", "n": 1, "ascending": False}]
    with pytest.raises(PipelineValidationError, match="읽을 테이블이"):
        validate_pipeline(operations, ws)
