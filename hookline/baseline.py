"""Naive rule-based baseline: the last ~45 s of every episode.

Episodes are written to end on a cliffhanger, so "cut the ending" is a fair, cheap baseline.
It ignores the hook rule, which is exactly what the LLM is meant to add.
"""
from __future__ import annotations

from .schemas import Candidate, ParseResult, Promo, SegmentRef
from .validate import dialogue_by_episode, validate_candidate

TAIL = 45.0


def baseline_promos(show: ParseResult, tail: float = TAIL) -> list[Promo]:
    index = show.beat_index()
    dialogue = dialogue_by_episode(index)
    out = []
    for ep in show.episodes:
        if not ep.beats:
            continue
        cut = max(0.0, ep.duration - tail)
        beats = sorted(ep.beats, key=lambda b: (b.start, b.id))
        first = next((b for b in beats if b.start >= cut), beats[0])
        last = max(beats, key=lambda b: (b.end, b.start))
        hook = next((b for b in beats if first.start <= b.start <= first.start + 3 and b.kind == "DIALOGUE"), first)
        c = Candidate(id=f"BASE-E{ep.num:02d}", kind="continuous", title=f"Last {tail:.0f}s of Ep {ep.num}",
                      segments=[SegmentRef(start_beat=first.id, end_beat=last.id)],
                      hook_beat=hook.id, cliff_beat=last.id, hook=hook.text[:80], cliffhanger=last.text[:80],
                      why="baseline: episode ending")
        p, _ = validate_candidate(c, index, dialogue)
        if p:
            p.kind = "baseline"
            out.append(p)
    return out
