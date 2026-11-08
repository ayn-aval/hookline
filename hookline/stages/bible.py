"""Stage 1: series bible (characters, aliases, arcs, reveals) from loglines and speaker labels."""
from __future__ import annotations

import json
from collections import Counter

from ..prompts import load_prompt
from ..schemas import ParseResult

MAX_SPEAKER_LABELS = 80


def make_bible(show: ParseResult, llm) -> dict:
    speakers = Counter(b.speaker for e in show.episodes for b in e.beats if b.speaker)
    episodes = "\n".join(f"Episode {e.num}: {e.logline}\n  Continuity: {e.continuity}" for e in show.episodes)
    labels = ", ".join(f"{s} ({n})" for s, n in speakers.most_common(MAX_SPEAKER_LABELS))
    user = f"EPISODES:\n{episodes}\n\nSPEAKER LABELS (count):\n{labels}"
    bible = llm.json(load_prompt("bible"), user, tag="01_bible")
    if not isinstance(bible, dict):
        bible = {}
    bible.setdefault("show_premise", "")
    bible.setdefault("reveals", [])
    return bible


def bible_text(bible: dict) -> str:
    return json.dumps(bible, ensure_ascii=False)
