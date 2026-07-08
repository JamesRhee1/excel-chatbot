"""Structured JSONL execution traces (metadata only — no DataFrames)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

_DEFAULT_TRACE_DIR = Path("./traces/")


@dataclass
class TraceRecord:
    trace_id: str
    timestamp: str
    user_message: str
    route_path: str
    intent: dict
    operations_applied: list[dict] = field(default_factory=list)
    per_op_ms: list[float] = field(default_factory=list)
    verification_summaries: list[str] = field(default_factory=list)
    answer_type: str = "message"
    error: str | None = None
    total_ms: float = 0.0
    input_rows: int | None = None
    input_columns: list[str] = field(default_factory=list)
    output_rows: int | None = None
    output_columns: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class TraceWriter:
    """Append-only JSONL trace writer."""

    def __init__(self, trace_dir: Path | str | None = None) -> None:
        self._trace_dir_override = Path(trace_dir) if trace_dir is not None else None

    @property
    def trace_dir(self) -> Path:
        if self._trace_dir_override is not None:
            return self._trace_dir_override
        env_dir = os.environ.get("EXCEL_CHATBOT_TRACE_DIR")
        return Path(env_dir or _DEFAULT_TRACE_DIR)

    def _path_for_today(self) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        return self.trace_dir / f"traces_{day}.jsonl"

    def write(self, record: TraceRecord) -> None:
        try:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            path = self._path_for_today()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(record.to_json())
                handle.write("\n")
        except OSError as exc:
            logger.warning("트레이스 기록 실패(처리는 계속됩니다): %s", exc)


def new_trace_id() -> str:
    return str(uuid4())


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
