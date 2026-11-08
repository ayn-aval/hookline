"""Plain-text renderings of beats, episodes and promo clips for prompts and the UI."""
from __future__ import annotations

from .parse import fmt_ts
from .schemas import Beat, Episode, ParseResult, Promo

KIND_LABEL = {"CAMERA": "CAM", "ACTION": "ACT", "SFX": "SFX", "OTHER": "OTHER"}


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _speaker(b: Beat) -> str:
    return b.speaker + (f" ({b.emotion})" if b.emotion else "")


def beat_line(b: Beat, cam_chars: int = 120) -> str:
    """`[E01-B007 00:11.3-00:13.1 MATRIARCH (Cold)] "line"` — the form the model refers to by ID."""
    span = f"{fmt_ts(b.start)[:-1]}-{fmt_ts(b.end)[:-1]}"
    if b.kind == "DIALOGUE":
        return f"[{b.id} {span} {_speaker(b)}] \"{b.text}\""
    text = _clip(b.text, cam_chars) if b.kind == "CAMERA" else b.text
    return f"[{b.id} {span} {KIND_LABEL[b.kind]}] {text}"


def episode_block(ep: Episode) -> str:
    head = f"EPISODE {ep.num} (duration {fmt_ts(ep.duration)})\nLogline: {ep.logline}\n"
    return head + "\n".join(beat_line(b) for b in ep.beats)


def promo_beats(p: Promo, show: ParseResult) -> list[tuple[float, Beat, int]]:
    """(offset from promo start, beat, segment number) for every beat in the promo, in play order."""
    out, offset = [], 0.0
    for n, seg in enumerate(p.segments):
        for b in sorted(show.episode(seg.ep).beats, key=lambda b: (b.start, b.id)):
            if seg.start <= b.start < seg.end:
                out.append((round(offset + b.start - seg.start, 1), b, n))
        offset += seg.end - seg.start
    return out


def promo_text(p: Promo, show: ParseResult) -> str:
    return " ".join(b.text for _, b, _ in promo_beats(p, show))


def clip_block(p: Promo, show: ParseResult) -> str:
    """A promo as a stranger would experience it: relative times only, no series context."""
    lines = [f"=== CLIP {p.id} ({p.duration:.0f}s) ==="]
    current_segment = 0
    for offset, b, seg in promo_beats(p, show):
        if seg != current_segment:
            lines.append("--- CUT ---")
            current_segment = seg
        if b.kind == "DIALOGUE":
            lines.append(f"+{offset:.1f} {_speaker(b)}: \"{b.text}\"")
        else:
            lines.append(f"+{offset:.1f} {KIND_LABEL[b.kind]}: {_clip(b.text, 140)}")
    return "\n".join(lines)
