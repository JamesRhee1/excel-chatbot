"""LLM pandas code generation for the escape-hatch path."""

from __future__ import annotations

import json
import logging
import re

from core.sandbox_runner import validate_code_static
from llm.client import OllamaConnectionError, OllamaModelNotFoundError, chat_plain

logger = logging.getLogger(__name__)

CODEGEN_SYSTEM = """\
You write short pandas code to answer the user's Excel question.

Rules (strict):
- The input DataFrame is already loaded as variable `df`
- You MUST assign the final answer to variable `result` (pandas DataFrame)
- Allowed libraries: pandas (pd) and numpy (np) only — they are pre-imported
- Do NOT import any module, access files, network, or environment
- Do NOT use open(), eval(), exec(), os, sys, subprocess, requests, or pathlib
- Keep code concise and deterministic

Dataset profile:
- columns: {column_names}
- numeric columns: {numeric_columns}
- text columns: {text_columns}
- sample values: {sample_values}

Return ONLY Python code. No explanation outside the code.
"""


def _extract_code(text: str) -> str:
    cleaned = text.strip()
    block = re.search(r"```(?:python)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
    if block:
        cleaned = block.group(1).strip()
    return cleaned


def generate_pandas_code(user_message: str, profile: dict, model: str | None = None) -> str | None:
    """Generate sandbox-ready pandas code, or None if generation/validation fails."""
    system_prompt = CODEGEN_SYSTEM.format(
        column_names=json.dumps(profile.get("column_names", []), ensure_ascii=False),
        numeric_columns=json.dumps(profile.get("numeric_columns", []), ensure_ascii=False),
        text_columns=json.dumps(profile.get("text_columns", []), ensure_ascii=False),
        sample_values=json.dumps(profile.get("sample_values_by_column", {}), ensure_ascii=False),
    )
    try:
        raw = chat_plain(system_prompt, user_message, model=model)
    except (OllamaConnectionError, OllamaModelNotFoundError) as exc:
        logger.warning("코드 생성 LLM 호출 실패: %s", exc)
        return None

    code = _extract_code(raw)
    if not code:
        return None
    try:
        validate_code_static(code)
    except Exception as exc:
        logger.warning("생성 코드 정적 검사 실패: %s", exc)
        return None
    return code
