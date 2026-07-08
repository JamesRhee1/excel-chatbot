"""Subprocess-isolated pandas code execution (escape hatch — disabled by default)."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

CHILD_SCRIPT = Path(__file__).resolve().parent / "sandbox_child.py"
DEFAULT_TIMEOUT_SEC = 15
DEFAULT_MEMORY_GB = 1.0
CODEGEN_ENV = "EXCEL_CHATBOT_ENABLE_CODEGEN"
CODEGEN_WARNING = (
    "⚠ 이 결과는 LLM 생성 코드로 계산되었으며 검증 계층이 적용되지 않았습니다"
)

# Static denylist — auxiliary only; primary safety is process isolation (see sandbox_child.py).
_DANGEROUS_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bimport\s+os\b",
        r"\bimport\s+sys\b",
        r"\bimport\s+subprocess\b",
        r"\bimport\s+socket\b",
        r"\bimport\s+requests\b",
        r"\bimport\s+pathlib\b",
        r"\bimport\s+shutil\b",
        r"\bimport\s+urllib\b",
        r"\bfrom\s+os\b",
        r"\bfrom\s+sys\b",
        r"\bfrom\s+subprocess\b",
        r"\bopen\s*\(",
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"__import__\s*\(",
        r"\bos\.",
        r"\bsubprocess\.",
        r"\bsocket\.",
    )
)


class SandboxError(RuntimeError):
    """Raised when sandboxed execution fails."""


def is_codegen_enabled() -> bool:
    return os.environ.get(CODEGEN_ENV, "").strip() == "1"


def validate_code_static(code: str) -> None:
    """Reject obviously dangerous code before subprocess launch (auxiliary guard)."""
    stripped = code.strip()
    if not stripped:
        raise SandboxError("실행할 코드가 비어 있습니다.")
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(stripped):
            raise SandboxError(f"허용되지 않는 코드 패턴이 감지되었습니다: {pattern.pattern}")


def _serialize_dataframe(df: pd.DataFrame, path: Path) -> None:
    df.to_json(path, orient="split", force_ascii=False)


def _deserialize_dataframe(path: Path) -> pd.DataFrame:
    return pd.read_json(path, orient="split")


def run_sandbox(
    code: str,
    df: pd.DataFrame,
    *,
    timeout: int = DEFAULT_TIMEOUT_SEC,
    memory_limit_gb: float = DEFAULT_MEMORY_GB,
) -> pd.DataFrame:
    """Execute pandas code in an isolated child process; input/output via JSON files only."""
    validate_code_static(code)

    if platform.system() == "Windows":
        logger.info("Windows 환경: sandbox 메모리 상한은 적용되지 않으며 timeout만 적용됩니다.")

    with tempfile.TemporaryDirectory(prefix="excel_chatbot_sandbox_") as tmp_dir:
        tmp = Path(tmp_dir)
        input_path = tmp / "input.json"
        output_path = tmp / "output.json"
        code_path = tmp / "user_code.py"
        meta_path = tmp / "meta.json"

        _serialize_dataframe(df, input_path)
        code_path.write_text(code, encoding="utf-8")
        meta_path.write_text(
            json.dumps({"memory_limit_gb": memory_limit_gb}),
            encoding="utf-8",
        )

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    str(CHILD_SCRIPT),
                    str(input_path),
                    str(output_path),
                    str(code_path),
                    str(meta_path),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(f"코드 실행이 {timeout}초 제한을 초과했습니다.") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "알 수 없는 오류").strip()
            raise SandboxError(detail)

        if not output_path.exists():
            raise SandboxError("샌드박스가 결과 파일을 생성하지 않았습니다.")

        result = _deserialize_dataframe(output_path)
        if not isinstance(result, pd.DataFrame):
            raise SandboxError("result는 pandas DataFrame이어야 합니다.")
        return result
