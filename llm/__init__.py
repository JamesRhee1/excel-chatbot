"""LLM layer: provider-backed chat integration."""

from llm.client import OllamaConnectionError, OllamaModelNotFoundError, chat
from llm.intent import IntentParseError, parse_intent
from llm.providers import get_provider, is_llm_available

__all__ = [
    "chat",
    "OllamaConnectionError",
    "OllamaModelNotFoundError",
    "get_provider",
    "is_llm_available",
    "parse_intent",
    "IntentParseError",
]
