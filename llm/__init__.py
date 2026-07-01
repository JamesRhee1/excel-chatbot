"""LLM layer: Ollama integration."""

from llm.client import OllamaConnectionError, OllamaModelNotFoundError, chat
from llm.intent import IntentParseError, parse_intent

__all__ = [
    "chat",
    "OllamaConnectionError",
    "OllamaModelNotFoundError",
    "parse_intent",
    "IntentParseError",
]
