"""The interface every pipeline stage depends on, so tests and other clients can stand in for LLM."""
from __future__ import annotations

from typing import Any, Protocol


class ModelConfig(Protocol):
    provider: str
    model: str
    temperature: float


class JSONModel(Protocol):
    cfg: ModelConfig
    usage: dict

    def json(self, system: str, user: str, tag: str) -> Any: ...
