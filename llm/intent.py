"""Intent parsing: natural language to structured JSON commands."""

from __future__ import annotations

import json
import re

from llm.client import chat

SYSTEM_PROMPT = """\
You are an Excel operation planner. Convert the user's natural-language request into a JSON object.

Available columns in the current Excel sheet:
{columns}

Return ONLY valid JSON matching this schema (no explanation, no markdown):
{{
  "operations": [
    {{"type": "filter", "column": "<column>", "op": ">", "value": <value>}},
    {{"type": "sort", "column": "<column>", "ascending": true}},
    {{"type": "select", "columns": ["<col1>", "<col2>"]}},
    {{"type": "aggregate", "group_by": ["<col>"], "agg_column": "<column>", "agg_func": "sum"}}
  ]
}}

Rules:
- Use only column names from the available columns list.
- filter op must be one of: >, <, >=, <=, ==, !=, contains
- aggregate agg_func must be one of: sum, mean, count, max, min
- If the request needs no operations, return {{"operations": []}}
"""


class IntentParseError(ValueError):
    """Raised when LLM output cannot be parsed into a valid intent."""


def parse_intent(
    user_message: str,
    columns: list[str],
    model: str | None = None,
) -> dict:
    """Convert a natural-language message into structured operation commands.

    Args:
        user_message: User's natural-language request.
        columns: Column names available in the current Excel sheet.
        model: Optional Ollama model override.

    Returns:
        Dict with an "operations" list of operation dicts.

    Raises:
        IntentParseError: If the LLM response is not valid JSON or missing required fields.
        OllamaConnectionError: If the Ollama server is unreachable.
        OllamaModelNotFoundError: If the requested model is not installed.
    """
    system_prompt = SYSTEM_PROMPT.format(columns=json.dumps(columns, ensure_ascii=False))
    raw_response = chat(system_prompt, user_message, model=model)
    intent = _extract_json(raw_response)
    _validate_intent(intent)
    return intent


def _extract_json(text: str) -> dict:
    """Extract and parse a JSON object from LLM output."""
    cleaned = text.strip()

    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
    if code_block:
        cleaned = code_block.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise IntentParseError(
                "LLM 응답에서 JSON을 파싱할 수 없습니다. "
                f"원본 응답: {text[:200]}"
            ) from exc

    raise IntentParseError(
        "LLM 응답에 유효한 JSON 객체가 없습니다. "
        f"원본 응답: {text[:200]}"
    )


def _validate_intent(intent: dict) -> None:
    """Validate the parsed intent structure."""
    if not isinstance(intent, dict):
        raise IntentParseError(
            f"의도 파싱 결과가 dict가 아닙니다: {type(intent).__name__}"
        )

    if "operations" not in intent:
        raise IntentParseError(
            '의도 JSON에 "operations" 키가 없습니다. '
            f"받은 키: {list(intent.keys())}"
        )

    if not isinstance(intent["operations"], list):
        raise IntentParseError(
            f'"operations"는 list여야 합니다: {type(intent["operations"]).__name__}'
        )

    for i, op in enumerate(intent["operations"]):
        if not isinstance(op, dict) or "type" not in op:
            raise IntentParseError(
                f"operations[{i}]에 'type' 필드가 없습니다: {op!r}"
            )
