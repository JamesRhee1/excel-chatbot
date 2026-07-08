"""Agent-layer access to the shared operation registry."""

from core.op_spec import (
    AGG_FUNCTIONS,
    ANSWER_TYPES,
    FILTER_OPERATORS,
    OPERATION_SPEC_BY_TYPE,
    OPERATION_SPECS,
    SUPPORTED_OPERATION_TYPES,
    OperationValidationError,
    build_json_schema_block,
    validate_answer_type,
    validate_operation,
    validate_operations,
)

__all__ = [
    "AGG_FUNCTIONS",
    "ANSWER_TYPES",
    "FILTER_OPERATORS",
    "OPERATION_SPEC_BY_TYPE",
    "OPERATION_SPECS",
    "SUPPORTED_OPERATION_TYPES",
    "OperationValidationError",
    "build_json_schema_block",
    "validate_answer_type",
    "validate_operation",
    "validate_operations",
]
