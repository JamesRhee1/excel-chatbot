"""Intent parsing: natural language to structured JSON commands."""

from __future__ import annotations

import json
import logging
import re

from core.op_spec import (
    build_json_schema_block,
    validate_answer_type,
    validate_operations,
)
from llm.client import chat

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an adaptive Excel assistant planner. Convert the user's natural-language request into a JSON object.

Dataset profile:
- available columns: {column_names}
- numeric columns: {numeric_columns}
- text columns: {text_columns}
- likely amount columns: {likely_amount_columns}
- likely name columns: {likely_name_columns}
- likely category columns: {likely_category_columns}
- sample values: {sample_values}

Return ONLY valid JSON matching this schema:
""" + build_json_schema_block() + """

Rules:
- NEVER invent numbers. Planning only.
- "가장 높은/낮은 행" => top_n (NOT aggregate)
- "<항목> 얼마" => value_answer
- "데이터 설명" => describe_dataset
- "할 수 있는 것" => help
- aggregate ONLY with explicit group (e.g. "분류별")
- NEVER aggregate without non-empty group_by
- If unsure, return clarify with an honest message that you cannot answer confidently
- NEVER return empty operations without clarify message
- filter op: >, <, >=, <=, ==, !=, <>, contains  (<> means not equal)
- Numeric filter values must be JSON numbers without quotes (e.g. "value": 0, not "0")
- Use exclude_summary implicitly via planner only when user asks to ignore total rows; executor auto-excludes 합계/소계 rows for ranking/sort/aggregate
- When user says "직전 결과에서", "여기서", or "이 중에서", set source to "last_result"
- For ratio/return rate/percent (%) requests, do NOT put formulas in column; plan derive (op="divide" or "percent") then top_n or sort. Example: "수익률이 가장 높은 행" => derive(new_column="수익률", left="이익", op="divide", right="매출") then top_n on "수익률"
- Placeholders in schema examples must be replaced with actual column names before returning JSON.
"""

def clarify_message(profile: dict | None = None) -> str:
    profile = profile or {}
    examples = profile.get("domain_clarify_examples") or [
        "'가장 높은 행 찾아줘'",
        "'항목이 얼마야?'",
        "'분류별 금액 합계 보여줘'",
    ]
    lines = [
        "죄송합니다. 이 질문에는 확실하게 답변드리기 어렵습니다.",
        "",
        "업로드된 엑셀 파일 기준으로 아래처럼 다시 질문해 주시면 도움을 드릴 수 있습니다.",
    ]
    lines.extend(f"- {example}" for example in examples)
    return "\n".join(lines)


def demo_mode_llm_message(profile: dict) -> str:
    examples = list(profile.get("domain_example_queries", [])[:2])
    if len(examples) < 2:
        fallback = ["가장 높은 행 찾아줘", "매출 상위 5개"]
        examples.extend(fallback[: 2 - len(examples)])
    example_text = ", ".join(f"'{q}'" for q in examples[:2])
    return (
        "이 질문은 LLM 해석이 필요합니다. 데모 환경에서는 정형 질의만 지원됩니다. "
        f"예: {example_text}"
    )


UNKNOWN_MESSAGE = clarify_message()
_CLARIFY_FALLBACK = UNKNOWN_MESSAGE


class IntentParseError(ValueError):
    """Raised when LLM output cannot be parsed into a valid intent."""


def parse_intent(user_message: str, profile: dict, model: str | None = None) -> dict:
    system_prompt = SYSTEM_PROMPT.format(
        column_names=json.dumps(profile.get("column_names", []), ensure_ascii=False),
        numeric_columns=json.dumps(profile.get("numeric_columns", []), ensure_ascii=False),
        text_columns=json.dumps(profile.get("text_columns", []), ensure_ascii=False),
        likely_amount_columns=json.dumps(profile.get("likely_amount_columns", []), ensure_ascii=False),
        likely_name_columns=json.dumps(profile.get("likely_name_columns", []), ensure_ascii=False),
        likely_category_columns=json.dumps(profile.get("likely_category_columns", []), ensure_ascii=False),
        sample_values=json.dumps(profile.get("sample_values_by_column", {}), ensure_ascii=False),
    )
    try:
        raw_response = chat(system_prompt, user_message, model=model)
        intent = _extract_json(raw_response)
    except IntentParseError:
        return _clarify_intent(clarify_message(profile))

    try:
        _validate_intent(intent, profile)
    except IntentParseError as exc:
        return _clarify_intent(str(exc))
    return intent


def _clarify_intent(message: str) -> dict:
    return {
        "answer_type": "message",
        "operations": [{"type": "clarify", "message": message}],
        "message": message,
        "final_response_instruction": "",
    }


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
    if code_block:
        cleaned = code_block.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("JSON 파싱 실패. LLM 응답 앞부분: %s", text[:200])
            raise IntentParseError(_CLARIFY_FALLBACK)
    logger.warning("JSON 파싱 실패. LLM 응답 앞부분: %s", text[:200])
    raise IntentParseError(_CLARIFY_FALLBACK)


def _validate_intent(intent: dict, profile: dict) -> None:
    if not isinstance(intent, dict):
        raise IntentParseError(f"의도 파싱 결과가 dict가 아닙니다: {type(intent).__name__}")
    if "operations" not in intent:
        raise IntentParseError('의도 JSON에 "operations" 키가 없습니다.')
    if not isinstance(intent["operations"], list):
        raise IntentParseError('"operations"는 list여야 합니다.')

    answer_type = intent.get("answer_type", "dataframe")
    validate_answer_type(answer_type, on_error=IntentParseError)

    if not intent["operations"]:
        if not intent.get("message", "").strip():
            raise IntentParseError("실행할 작업이 없습니다.")
        return

    validate_operations(intent["operations"], on_error=IntentParseError)
