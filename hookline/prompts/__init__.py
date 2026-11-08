"""Versioned prompt templates (Markdown files in this folder)."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def prompts_sha() -> str:
    """Short fingerprint of all prompts, recorded with every run."""
    digest = hashlib.sha256()
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]
