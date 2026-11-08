"""Small helpers for splitting work into LLM-call-sized batches."""
from __future__ import annotations

from typing import Sequence, TypeVar

T = TypeVar("T")


def chunked(items: Sequence[T], size: int) -> list[list[T]]:
    size = max(1, size)
    return [list(items[i:i + size]) for i in range(0, len(items), size)]
