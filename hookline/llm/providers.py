"""Provider presets and model configuration.

Every supported provider exposes an OpenAI-compatible chat-completions API, so switching
models is a matter of choosing a preset (base URL) plus a model name and key.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

PROVIDERS: dict[str, dict[str, str]] = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "default_model": "gemini-3.5-flash-lite", "judge_model": "gemini-3.1-flash-lite",
               "key_env": "GEMINI_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1/",
               "default_model": "gpt-5-mini", "key_env": "OPENAI_API_KEY"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1/",
                  "default_model": "claude-sonnet-5-5", "key_env": "ANTHROPIC_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1/",
             "default_model": "llama-3.3-70b-versatile", "key_env": "GROQ_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1/",
                   "default_model": "openrouter/auto", "key_env": "OPENROUTER_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1/",
               "default_model": "qwen3:8b", "key_env": "OLLAMA_API_KEY"},
    "custom": {"base_url": "http://localhost:8000/v1/",
               "default_model": "", "key_env": "HOOKLINE_API_KEY"},
}

DEFAULT_PROVIDER = "gemini"


@dataclass
class LLMConfig:
    provider: str = DEFAULT_PROVIDER
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.4

    def __post_init__(self) -> None:
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}; choose from {sorted(PROVIDERS)}")
        if not self.model:
            self.model = PROVIDERS[self.provider]["default_model"]

    def resolved_base_url(self) -> str:
        return self.base_url or PROVIDERS[self.provider]["base_url"]

    def resolved_key(self) -> str:
        return (self.api_key or os.getenv("HOOKLINE_API_KEY")
                or os.getenv(PROVIDERS[self.provider]["key_env"]) or "none")

    @classmethod
    def from_env(cls, **overrides) -> "LLMConfig":
        """Build from HOOKLINE_* environment variables; explicit non-None overrides win."""
        values = dict(
            provider=os.getenv("HOOKLINE_PROVIDER", DEFAULT_PROVIDER),
            model=os.getenv("HOOKLINE_MODEL") or None,
            api_key=os.getenv("HOOKLINE_API_KEY") or None,
            base_url=os.getenv("HOOKLINE_BASE_URL") or None,
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
