"""Single source of truth for intent operation schema and validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from core.operations import normalize_filter_op

FILTER_OPERATORS = frozenset({">", "<", ">=", "<=", "==", "!=", "<>", "contains"})
AGG_FUNCTIONS = frozenset({"sum", "mean", "count", "max", "min"})
ANSWER_TYPES = frozenset({"dataframe", "message", "mixed"})
INPUT_TYPES = frozenset({"table", "none"})
OUTPUT_TYPES = frozenset({"table", "scalar", "message"})

InputType = Literal["table", "none"]
OutputType = Literal["table", "scalar", "message"]


@dataclass(frozen=True)
class OpSpec:
    type: str
    required_fields: tuple[str, ...] = ()
    prompt_example: str | None = None
    include_in_llm_prompt: bool = False
    require_nonempty_group_by: bool = False
    require_message: bool = False
    input_type: InputType = "table"
    output_type: OutputType = "table"
    allows_source: bool = True
    allows_save_as: bool = True


# Order matches the original SYSTEM_PROMPT examples block.
OPERATION_SPECS: tuple[OpSpec, ...] = (
    OpSpec(
        "top_n",
        required_fields=("column",),
        prompt_example='{"type": "top_n", "column": "<expr>", "n": 1, "ascending": false}',
        include_in_llm_prompt=True,
    ),
    OpSpec(
        "lookup",
        required_fields=("query",),
        prompt_example='{"type": "lookup", "query": "<text>"}',
        include_in_llm_prompt=True,
    ),
    OpSpec(
        "value_answer",
        required_fields=("row_query",),
        prompt_example='{"type": "value_answer", "row_query": "<item>"}',
        include_in_llm_prompt=True,
        output_type="table",
    ),
    OpSpec(
        "describe_dataset",
        prompt_example='{"type": "describe_dataset"}',
        include_in_llm_prompt=True,
    ),
    OpSpec(
        "help",
        prompt_example='{"type": "help"}',
        include_in_llm_prompt=True,
        input_type="none",
        output_type="message",
        allows_source=False,
        allows_save_as=False,
    ),
    OpSpec(
        "clarify",
        prompt_example='{"type": "clarify", "message": "<ask user to rephrase>"}',
        include_in_llm_prompt=True,
        require_message=True,
        input_type="none",
        output_type="message",
        allows_source=False,
        allows_save_as=False,
    ),
    OpSpec(
        "filter",
        required_fields=("column", "op", "value"),
        prompt_example=(
            '{"type": "filter", "source": "main", "column": "<expr>", "op": ">", '
            '"value": 0, "save_as": "filtered"}'
        ),
        include_in_llm_prompt=True,
    ),
    OpSpec(
        "sort",
        required_fields=("column",),
        prompt_example='{"type": "sort", "column": "<expr>", "ascending": false}',
        include_in_llm_prompt=True,
    ),
    OpSpec(
        "aggregate",
        required_fields=("group_by", "agg_column", "agg_func"),
        prompt_example='{"type": "aggregate", "group_by": ["<col>"], "agg_column": "<col>", "agg_func": "sum"}',
        include_in_llm_prompt=True,
        require_nonempty_group_by=True,
    ),
    OpSpec(
        "summary_stats",
        required_fields=("column",),
        prompt_example='{"type": "summary_stats", "column": "<expr>"}',
        include_in_llm_prompt=True,
        output_type="scalar",
    ),
    OpSpec("select", required_fields=("columns",)),
    OpSpec("exclude_summary"),
    OpSpec("filter_row_type"),
    OpSpec(
        "combine_dataset",
        input_type="table",
        output_type="table",
        allows_source=True,
    ),
    OpSpec(
        "summarize_by_file",
        required_fields=("value_column",),
        input_type="table",
        output_type="table",
    ),
    OpSpec(
        "compare_item_across_files",
        required_fields=("item_query",),
        input_type="table",
        output_type="table",
    ),
    OpSpec(
        "top_n_by_file",
        required_fields=("value_column",),
        input_type="table",
        output_type="table",
    ),
    OpSpec(
        "top_n_overall",
        required_fields=("value_column",),
        input_type="table",
        output_type="table",
    ),
    OpSpec(
        "multi_summary",
        input_type="table",
        output_type="message",
        allows_save_as=False,
    ),
    OpSpec(
        "derive",
        required_fields=("new_column", "left", "op", "right"),
        prompt_example=(
            '{"type": "derive", "new_column": "차이", "left": "<col>", '
            '"op": "subtract", "right": "<col|number>"}'
        ),
        include_in_llm_prompt=True,
    ),
)

OPERATION_SPEC_BY_TYPE: dict[str, OpSpec] = {spec.type: spec for spec in OPERATION_SPECS}
SUPPORTED_OPERATION_TYPES = frozenset(OPERATION_SPEC_BY_TYPE)


class OperationValidationError(ValueError):
    """Raised when an operation dict fails schema validation."""


class PipelineValidationError(ValueError):
    """Raised when an operation pipeline fails workspace/type validation."""


def build_json_schema_block() -> str:
    """Build the JSON schema example block for the LLM system prompt."""
    examples = [
        spec.prompt_example
        for spec in OPERATION_SPECS
        if spec.include_in_llm_prompt and spec.prompt_example
    ]
    joined = ",\n    ".join(example.replace("{", "{{").replace("}", "}}") for example in examples)
    return (
        "{{\n"
        '  "answer_type": "dataframe" | "message" | "mixed",\n'
        '  "operations": [\n'
        f"    {joined}\n"
        "  ],\n"
        '  "message": "",\n'
        '  "final_response_instruction": "short instruction for how to explain result"\n'
        "}}"
    )


def _require_fields(
    op: dict,
    index: int,
    fields: tuple[str, ...],
    *,
    on_error: Callable[[str], Exception],
) -> None:
    for field in fields:
        if field not in op:
            raise on_error(
                f"operations[{index}] ({op.get('type', '?')})에 '{field}' 필드가 없습니다."
            )


def _validate_optional_pipeline_fields(op: dict, index: int, spec: OpSpec, *, on_error: Callable[[str], Exception]) -> None:
    source = op.get("source")
    save_as = op.get("save_as")

    if source is not None:
        if not spec.allows_source:
            raise on_error(f"operations[{index}] ({spec.type})는 source를 지정할 수 없습니다.")
        if not isinstance(source, str) or not source.strip():
            raise on_error(f"operations[{index}] source는 비어 있지 않은 문자열이어야 합니다.")

    if save_as is not None:
        if not spec.allows_save_as:
            raise on_error(f"operations[{index}] ({spec.type})는 save_as를 지정할 수 없습니다.")
        if not isinstance(save_as, str) or not save_as.strip():
            raise on_error(f"operations[{index}] save_as는 비어 있지 않은 문자열이어야 합니다.")
        if spec.output_type != "table":
            raise on_error(f"operations[{index}] ({spec.type})는 테이블 결과가 없어 save_as를 사용할 수 없습니다.")


def validate_operation(
    op: dict,
    index: int,
    *,
    on_error: Callable[[str], Exception] | None = None,
) -> None:
    """Validate and normalize a single operation dict in place."""
    error = on_error or OperationValidationError

    if not isinstance(op, dict) or "type" not in op:
        raise error(f"operations[{index}] 형식이 올바르지 않습니다.")

    op_type = op["type"]
    if op_type not in SUPPORTED_OPERATION_TYPES:
        raise error(f"지원하지 않는 작업 type: {op_type!r}")

    spec = OPERATION_SPEC_BY_TYPE[op_type]
    _require_fields(op, index, spec.required_fields, on_error=error)
    _validate_optional_pipeline_fields(op, index, spec, on_error=error)

    if spec.require_nonempty_group_by and not op.get("group_by"):
        raise error("group_by가 비어 있습니다. aggregate 대신 top_n을 사용하세요.")

    if spec.require_message and not op.get("message"):
        raise error("clarify에는 message가 필요합니다.")

    if op_type == "filter":
        normalized_op = normalize_filter_op(op["op"])
        if normalized_op not in FILTER_OPERATORS:
            raise error(f"filter op 오류: {op['op']!r}")
        op["op"] = normalized_op
    elif op_type == "aggregate" and op["agg_func"] not in AGG_FUNCTIONS:
        raise error(f"agg_func 오류: {op['agg_func']!r}")


def validate_operations(
    operations: list[dict],
    *,
    on_error: Callable[[str], Exception] | None = None,
) -> None:
    for index, op in enumerate(operations):
        validate_operation(op, index, on_error=on_error)


def validate_answer_type(answer_type: str, *, on_error: Callable[[str], Exception] | None = None) -> None:
    error = on_error or OperationValidationError
    if answer_type not in ANSWER_TYPES:
        raise error(f"answer_type이 올바르지 않습니다: {answer_type!r}")


def validate_pipeline(
    operations: list[dict],
    workspace,
    *,
    on_error: Callable[[str], Exception] | None = None,
) -> None:
    """Validate operation pipeline against workspace tables and type flow."""
    error = on_error or PipelineValidationError
    if not operations:
        return

    errors: list[str] = []
    prev_output: OutputType | None = None
    default_table = workspace.list_tables()[0] if workspace.list_tables() else None

    for index, op in enumerate(operations):
        try:
            validate_operation(op, index, on_error=error)
        except (OperationValidationError, PipelineValidationError) as exc:
            errors.append(str(exc))
            continue

        spec = OPERATION_SPEC_BY_TYPE[op["type"]]
        source = op.get("source")

        if spec.input_type == "table":
            if source:
                if workspace.get(source) is None:
                    errors.append(
                        f"operations[{index}] ({spec.type}): source 테이블 "
                        f"'{source}'이(가) 워크스페이스에 없습니다."
                    )
            elif index == 0:
                if default_table is None:
                    errors.append(
                        f"operations[{index}] ({spec.type}): 읽을 테이블이 워크스페이스에 없습니다."
                    )
            elif prev_output != "table":
                errors.append(
                    f"operations[{index}] ({spec.type}): 직전 작업 결과가 테이블이 아니라 "
                    "연속 실행할 수 없습니다. source를 지정하세요."
                )
        elif source:
            errors.append(
                f"operations[{index}] ({spec.type}): 이 작업은 source를 지정할 수 없습니다."
            )

        if index > 0 and prev_output == "message" and spec.input_type == "table":
            errors.append(
                f"operations[{index}] ({spec.type}): 메시지 결과 이후에는 테이블 작업을 "
                "이어서 실행할 수 없습니다."
            )

        prev_output = spec.output_type

    if errors:
        raise error("\n".join(errors))
