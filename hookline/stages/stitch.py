"""Stage 3: stitched promos built from the catalogue of moments mined in every episode."""
from __future__ import annotations

from ..prompts import load_prompt
from ..render import beat_line
from ..schemas import Candidate, ParseResult, SegmentRef
from .bible import bible_text

CONTEXT_SECONDS = 12.0


def _merged_windows(spans: list[list[float]]) -> list[list[float]]:
    spans = sorted(spans)
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def moment_catalogue(show: ParseResult, mined: dict[int, dict]) -> str:
    """Each mined moment with ~12 s of surrounding beats, so the model can choose segment edges."""
    index = show.beat_index()
    blocks = []
    for ep_num in sorted(mined):
        moments = [m for m in (mined[ep_num].get("moments") or [])
                   if isinstance(m, dict) and str(m.get("beat")) in index]
        if not moments:
            continue
        ep = show.episode(ep_num)
        spans = [[index[str(m["beat"])].start - CONTEXT_SECONDS, index[str(m["beat"])].end + CONTEXT_SECONDS]
                 for m in moments]
        notes = "; ".join(f"{m['beat']} = {m.get('type', '?')}: {m.get('note', '')}" for m in moments)
        lines = [f"## EPISODE {ep_num} — {ep.logline}", f"Moments: {notes}"]
        for start, end in _merged_windows(spans):
            lines += [beat_line(b, cam_chars=80) for b in ep.beats if start <= b.start <= end]
            lines.append("…")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def stitch(show: ParseResult, bible: dict, mined: dict[int, dict], llm) -> list[Candidate]:
    catalogue = moment_catalogue(show, mined)
    if not catalogue:
        return []
    user = f"SERIES BIBLE:\n{bible_text(bible)}\n\nMOMENT CATALOGUE:\n{catalogue}"
    out = llm.json(load_prompt("stitch"), user, tag="03_stitch")
    candidates = []
    for i, c in enumerate((out or {}).get("promos") or [], 1):
        try:
            segments = [SegmentRef(start_beat=str(s["start_beat"]), end_beat=str(s["end_beat"]))
                        for s in c["segments"]]
            candidates.append(Candidate(
                id=f"S{i:02d}", kind="stitched", title=str(c.get("title", "")), segments=segments,
                hook_beat=str(c.get("hook_beat") or segments[0].start_beat),
                cliff_beat=str(c.get("cliff_beat") or segments[-1].end_beat),
                hook=str(c.get("hook", "")), cliffhanger=str(c.get("cliffhanger", "")),
                why=str(c.get("why", ""))))
        except (AttributeError, KeyError, TypeError, ValueError, IndexError):
            continue
    return candidates
