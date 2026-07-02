"""Intent parsing: natural language to structured JSON commands."""

from __future__ import annotations

import json
import logging
import re

from agent.router import route_query
from core.operations import normalize_filter_op
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
{{
  "answer_type": "dataframe" | "message" | "mixed",
  "operations": [
    {{"type": "top_n", "column": "<expr>", "n": 1, "ascending": false}},
    {{"type": "lookup", "query": "<text>"}},
    {{"type": "value_answer", "row_query": "<item>"}},
    {{"type": "describe_dataset"}},
    {{"type": "help"}},
    {{"type": "clarify", "message": "<ask user to rephrase>"}},
    {{"type": "filter", "column": "<expr>", "op": ">", "value": 0}},
    {{"type": "sort", "column": "<expr>", "ascending": false}},
    {{"type": "aggregate", "group_by": ["<col>"], "agg_column": "<col>", "agg_func": "sum"}},
    {{"type": "summary_stats", "column": "<expr>"}}
  ],
  "message": "",
  "final_response_instruction": "short instruction for how to explain result"
}}

Rules:
- NEVER invent numbers. Planning only.
- "가장 높은/낮은 행" => top_n (NOT aggregate)
- "<항목> 얼마" => value_answer
- "데이터 설명" => describe_dataset
- "할 수 있는 것" => help
- aggregate ONLY with explicit group (e.g. "비목분류별")
- NEVER aggregate without non-empty group_by
- If unsure, return clarify with an honest message that you cannot answer confidently
- NEVER return empty operations without clarify message
- filter op: >, <, >=, <=, ==, !=, <>, contains  (<> means not equal)
- Use exclude_summary implicitly via planner only when user asks to ignore total rows; executor auto-excludes 합계/소계 rows for ranking/sort/aggregate
"""

_SUPPORTED_TYPES = frozenset(
    {
        "filter", "sort", "select", "aggregate", "top_n", "lookup",
        "describe_dataset", "value_answer", "help", "summary_stats", "clarify",
        "exclude_summary", "filter_row_type",
    }
)
_FILTER_OPS = frozenset({">", "<", ">=", "<=", "==", "!=", "<>", "contains"})
_AGG_FUNCS = frozenset({"sum", "mean", "count", "max", "min"})
UNKNOWN_MESSAGE = (
    "죄송합니다. 이 질문에는 확실하게 답변드리기 어렵습니다.\n\n"
    "업로드된 엑셀 파일 기준으로 아래처럼 다시 질문해 주시면 도움을 드릴 수 있습니다.\n"
    "- '당년도예산이 가장 높은 행 찾아줘' (합계/소계 행은 자동 제외)\n"
    "- '인쇄비가 얼마야?'\n"
    "- '비목분류별 당년도예산 합계 보여줘'"
)
_CLARIFY_FALLBACK = UNKNOWN_MESSAGE


class IntentParseError(ValueError):
    """Raised when LLM output cannot be parsed into a valid intent."""


def parse_intent(user_message: str, profile: dict, model: str | None = None) -> dict:
    routed = route_query(user_message, profile)
    if routed is not None:
        _validate_intent(routed, profile)
        return routed

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
        return _clarify_intent(_CLARIFY_FALLBACK)

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
    if answer_type not in ("dataframe", "message", "mixed"):
        raise IntentParseError(f'answer_type이 올바르지 않습니다: {answer_type!r}')

    if not intent["operations"]:
        if not intent.get("message", "").strip():
            raise IntentParseError("실행할 작업이 없습니다.")
        return

    for i, op in enumerate(intent["operations"]):
        if not isinstance(op, dict) or "type" not in op:
            raise IntentParseError(f"operations[{i}] 형식이 올바르지 않습니다.")
        op_type = op["type"]
        if op_type not in _SUPPORTED_TYPES:
            raise IntentParseError(f"지원하지 않는 작업 type: {op_type!r}")

        if op_type == "filter":
            _require_fields(op, i, "column", "op", "value")
            normalized_op = normalize_filter_op(op["op"])
            if normalized_op not in _FILTER_OPS:
                raise IntentParseError(f"filter op 오류: {op['op']!r}")
            op["op"] = normalized_op
        elif op_type == "sort":
            _require_fields(op, i, "column")
        elif op_type == "select":
            _require_fields(op, i, "columns")
        elif op_type == "aggregate":
            _require_fields(op, i, "group_by", "agg_column", "agg_func")
            if not op["group_by"]:
                raise IntentParseError("group_by가 비어 있습니다. aggregate 대신 top_n을 사용하세요.")
            if op["agg_func"] not in _AGG_FUNCS:
                raise IntentParseError(f"agg_func 오류: {op['agg_func']!r}")
        elif op_type == "top_n":
            _require_fields(op, i, "column")
        elif op_type == "lookup":
            _require_fields(op, i, "query")
        elif op_type == "value_answer":
            _require_fields(op, i, "row_query")
        elif op_type == "summary_stats":
            _require_fields(op, i, "column")
        elif op_type == "clarify":
            if not op.get("message"):
                raise IntentParseError("clarify에는 message가 필요합니다.")
        elif op_type == "exclude_summary":
            pass


def _require_fields(op: dict, index: int, *fields: str) -> None:
    for field in fields:
        if field not in op:
            raise IntentParseError(
                f"operations[{index}] ({op.get('type', '?')})에 '{field}' 필드가 없습니다."
            )
