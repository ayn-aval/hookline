"""Model-agnostic LLM access (any OpenAI-compatible endpoint)."""
from .client import LLM, LLMError
from .jsonparse import parse_json_text
from .protocol import JSONModel
from .providers import DEFAULT_PROVIDER, PROVIDERS, SUGGESTED_MODELS, LLMConfig

__all__ = ["LLM", "LLMConfig", "LLMError", "JSONModel", "PROVIDERS", "SUGGESTED_MODELS", "DEFAULT_PROVIDER", "parse_json_text"]
