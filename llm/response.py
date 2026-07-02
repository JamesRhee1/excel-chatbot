"""Natural-language response generation — delegates to response_formatter."""

from __future__ import annotations

from agent.response_formatter import format_user_response


def generate_response(
    user_query: str,
    intent: dict,
    execution: dict,
    profile: dict,
) -> str:
    """Build final user-facing message only."""
    message, _, _ = format_user_response(user_query, intent, execution, profile)
    return message
