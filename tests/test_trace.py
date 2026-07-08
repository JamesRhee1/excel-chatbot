"""Tests for JSONL execution traces."""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest

from agent.executor import run
from core.trace import TraceRecord, TraceWriter, new_trace_id


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "이름": ["김철수", "이영희", "박민수"],
            "부서": ["영업", "개발", "영업"],
            "매출": [1000, 2500, 800],
        }
    )


@pytest.fixture
def sample_excel(tmp_path, sample_df: pd.DataFrame) -> str:
    path = tmp_path / "sample.xlsx"
    sample_df.to_excel(path, index=False)
    return str(path)


def test_trace_record_json_format() -> None:
    record = TraceRecord(
        trace_id=new_trace_id(),
        timestamp="2026-07-08T00:00:00+00:00",
        user_message="매출 상위 3개",
        route_path="rule",
        intent={"answer_type": "dataframe", "operations": [{"type": "top_n", "n": 3}]},
        operations_applied=[{"type": "top_n", "n": 3}],
        per_op_ms=[12.5],
        verification_summaries=["2개 검사 모두 통과"],
        answer_type="dataframe",
        error=None,
        total_ms=45.2,
        input_rows=10,
        input_columns=["이름", "매출"],
        output_rows=3,
        output_columns=["이름", "매출"],
    )
    payload = json.loads(record.to_json())
    assert payload["route_path"] == "rule"
    assert payload["operations_applied"][0]["type"] == "top_n"
    assert "df" not in payload
    assert payload["input_rows"] == 10


def test_trace_writer_appends_jsonl(tmp_path) -> None:
    writer = TraceWriter(trace_dir=tmp_path)
    record = TraceRecord(
        trace_id="abc-123",
        timestamp="2026-07-08T00:00:00+00:00",
        user_message="도움말",
        route_path="rule",
        intent={"operations": [{"type": "help"}]},
    )
    writer.write(record)
    files = list(tmp_path.glob("traces_*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").strip()
    assert json.loads(line)["trace_id"] == "abc-123"


def test_trace_write_failure_does_not_break_run(sample_excel, monkeypatch) -> None:
    def _raise_os_error(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("core.trace.Path.mkdir", _raise_os_error)
    result = run(file_path=sample_excel, user_message="도움말")
    assert result["success"]
    assert result.get("trace_id")


def test_run_includes_trace_id_and_writes_file(sample_excel, tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EXCEL_CHATBOT_TRACE_DIR", str(tmp_path))
    result = run(file_path=sample_excel, user_message="데이터 설명해줘")
    assert result["success"]
    assert result.get("trace_id")
    files = list(tmp_path.glob("traces_*.jsonl"))
    assert files
    payload = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["trace_id"] == result["trace_id"]
    assert payload["route_path"] == "rule"
