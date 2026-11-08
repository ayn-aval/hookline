"""Turn LLM candidates (beat IDs) into promos with real, checked timestamps.

The promo rules are enforced here in code rather than trusted to the model:
  * every timestamp comes from a real beat (unknown IDs are rejected)
  * no cut lands in the middle of a spoken line
  * the hook starts within 3 s of the promo start
  * the promo ends on the cliffhanger beat
  * total length is 20-60 s (over-long windows are condensed, short ones lengthened where possible)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from .rules import (CLIFF_TOLERANCE, CONDENSE_HEAD, CONDENSE_TAIL, DEDUPE_IOU, HOOK_WINDOW, MAX_DURATION,
                    MIN_DURATION)
from .schemas import Beat, Candidate, Promo, Segment

BeatsByEpisode = dict[int, list[Beat]]


@dataclass
class _Span:
    ep: int
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def dialogue_by_episode(index: dict[str, Beat]) -> BeatsByEpisode:
    by_ep: BeatsByEpisode = defaultdict(list)
    for b in index.values():
        if b.kind == "DIALOGUE":
            by_ep[b.ep].append(b)
    return by_ep


def beats_by_episode(index: dict[str, Beat]) -> BeatsByEpisode:
    by_ep: BeatsByEpisode = defaultdict(list)
    for b in index.values():
        by_ep[b.ep].append(b)
    for beats in by_ep.values():
        beats.sort(key=lambda b: (b.start, b.id))
    return by_ep


def _total(spans: list[_Span]) -> float:
    return round(sum(s.length for s in spans), 2)


def _snap(ep_dialogue: list[Beat], start: float, end: float) -> tuple[float, float]:
    """Widen [start, end] until no spoken line is cut mid-way."""
    changed = True
    while changed:
        changed = False
        for d in ep_dialogue:
            if d.start < start < d.end:
                start, changed = d.start, True
            if d.start < end < d.end:
                end, changed = d.end, True
    return round(start, 2), round(end, 2)


def _extend_before_hook(span: _Span, hook: Beat, ep_beats: list[Beat], ep_dialogue: list[Beat]) -> bool:
    """Open up to HOOK_WINDOW seconds before the hook to reach the minimum length."""
    earlier = [b.start for b in ep_beats if hook.start - HOOK_WINDOW <= b.start < span.start]
    if not earlier:
        return False
    start, _ = _snap(ep_dialogue, min(earlier), span.end)
    if hook.start - start > HOOK_WINDOW:
        return False
    span.start = start
    return True


def _lengthen_run_up(spans: list[_Span], ep_beats: list[Beat], ep_dialogue: list[Beat]) -> bool:
    """Start the last segment earlier until the promo reaches MIN_DURATION, without overlapping earlier ones."""
    last = spans[-1]
    floor = max((s.end for s in spans[:-1] if s.ep == last.ep and s.end <= last.start), default=0.0)
    needed = MIN_DURATION - _total(spans)
    options = [b.start for b in ep_beats if floor <= b.start <= last.start - needed]
    if not options:
        return False
    start, _ = _snap(ep_dialogue, max(options), last.end)
    if start < floor:
        return False
    last.start = start
    return True


def _condense(span: _Span, ep_beats: list[Beat], ep_dialogue: list[Beat]) -> Optional[list[_Span]]:
    """Split an over-long window into the hook opening and the run-up to the cliffhanger."""
    head_ends = [b.end for b in ep_beats if b.end >= span.start + CONDENSE_HEAD]
    tail_starts = [b.start for b in ep_beats if b.start <= span.end - CONDENSE_TAIL]
    if not head_ends or not tail_starts:
        return None
    s1, e1 = _snap(ep_dialogue, span.start, min(head_ends))
    s2, e2 = _snap(ep_dialogue, max(tail_starts), span.end)
    if e1 >= s2 or (e1 - s1) + (e2 - s2) > MAX_DURATION:
        return None
    return [_Span(span.ep, s1, e1), _Span(span.ep, s2, e2)]


def _edge_ids(ep_beats: list[Beat], start: float, end: float) -> tuple[str, str]:
    first = min(ep_beats, key=lambda b: (abs(b.start - start), b.start))
    last = min(ep_beats, key=lambda b: (abs(b.end - end), -b.start))
    return first.id, last.id


def _overlapping_pair(spans: list[_Span]) -> Optional[tuple[int, int]]:
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            a, b = spans[i], spans[j]
            if a.ep == b.ep and a.start < b.end and b.start < a.end:
                return i + 1, j + 1
    return None


def validate_candidate(c: Candidate, index: dict[str, Beat], dialogue_by_ep: Optional[BeatsByEpisode] = None,
                       beats_by_ep: Optional[BeatsByEpisode] = None) -> tuple[Optional[Promo], list[str]]:
    """Return (promo, notes). The promo is None when the candidate cannot be made valid; notes say why."""
    dialogue_by_ep = dialogue_by_ep if dialogue_by_ep is not None else dialogue_by_episode(index)
    beats_by_ep = beats_by_ep if beats_by_ep is not None else beats_by_episode(index)
    repairs: list[str] = []
    kind = c.kind

    referenced = [x for s in c.segments for x in (s.start_beat, s.end_beat)] + [c.hook_beat, c.cliff_beat]
    unknown = sorted({i for i in referenced if i not in index})
    if unknown:
        return None, [f"{c.id}: unknown beat id(s) {unknown}"]
    if not c.segments:
        return None, [f"{c.id}: no segments"]

    spans: list[_Span] = []
    for s in c.segments:
        a, b = index[s.start_beat], index[s.end_beat]
        if a.ep != b.ep:
            return None, [f"{c.id}: segment {s.start_beat}->{s.end_beat} spans two episodes"]
        if b.start < a.start:
            return None, [f"{c.id}: reversed segment {s.start_beat}->{s.end_beat}"]
        spans.append(_Span(a.ep, a.start, max(a.end, b.end)))

    hook, first = index[c.hook_beat], spans[0]
    if hook.ep != first.ep or hook.start > first.end:
        return None, [f"{c.id}: hook beat {c.hook_beat} is not inside the first segment"]
    if hook.start - first.start > HOOK_WINDOW or hook.start < first.start:
        repairs.append(f"start moved {first.start:.1f}s -> {hook.start:.1f}s to open on the hook")
        first.start = hook.start

    cliff, last = index[c.cliff_beat], spans[-1]
    if cliff.ep != last.ep or cliff.end < last.start:
        return None, [f"{c.id}: cliffhanger beat {c.cliff_beat} is not inside the last segment"]
    if abs(last.end - cliff.end) > CLIFF_TOLERANCE:
        repairs.append(f"end moved {last.end:.1f}s -> {cliff.end:.1f}s to cut on the cliffhanger")
        last.end = cliff.end

    for span in spans:
        start, end = _snap(dialogue_by_ep.get(span.ep, []), span.start, span.end)
        if (start, end) != (round(span.start, 2), round(span.end, 2)):
            repairs.append(f"ep{span.ep} cut widened to {start:.1f}-{end:.1f}s so no line is cut mid-sentence")
        span.start, span.end = start, end
        if span.end <= span.start:
            return None, [f"{c.id}: empty segment after repairs"]

    if hook.start - spans[0].start > HOOK_WINDOW:
        return None, [f"{c.id}: hook lands {hook.start - spans[0].start:.1f}s in (>3s) even after repair"]

    total = _total(spans)
    first_ep, last_ep = spans[0].ep, spans[-1].ep
    if total < MIN_DURATION and len(spans) > 1 and _lengthen_run_up(
            spans, beats_by_ep[last_ep], dialogue_by_ep.get(last_ep, [])):
        repairs.append(f"last segment starts earlier ({spans[-1].start:.1f}s) for a longer run-up to the cliffhanger")
    elif total < MIN_DURATION and _extend_before_hook(spans[0], hook, beats_by_ep[first_ep],
                                                     dialogue_by_ep.get(first_ep, [])):
        repairs.append(f"start moved to {spans[0].start:.1f}s, up to 3s before the hook, to reach {MIN_DURATION:.0f}s")
    elif total > MAX_DURATION and len(spans) == 1:
        condensed = _condense(spans[0], beats_by_ep[first_ep], dialogue_by_ep.get(first_ep, []))
        if condensed:
            spans, kind = condensed, "stitched"
            repairs.append(f"{total:.0f}s window condensed to the hook opening plus the run-up to the cliffhanger")

    pair = _overlapping_pair(spans)
    if pair:
        return None, [f"{c.id}: segments {pair[0]} and {pair[1]} overlap in ep{spans[pair[0] - 1].ep}"]
    total = _total(spans)
    if total < MIN_DURATION:
        return None, [f"{c.id}: too short ({total:.1f}s < {MIN_DURATION:.0f}s)"]
    if total > MAX_DURATION:
        return None, [f"{c.id}: too long ({total:.1f}s > {MAX_DURATION:.0f}s)"]

    segments = []
    for span in spans:
        start_id, end_id = _edge_ids(beats_by_ep[span.ep], span.start, span.end)
        segments.append(Segment(ep=span.ep, start=span.start, end=span.end, start_beat=start_id, end_beat=end_id))
    promo = Promo(id=c.id, kind=kind, title=c.title, segments=segments, duration=total, hook=c.hook,
                  cliffhanger=c.cliffhanger, why=c.why, hook_beat=c.hook_beat, cliff_beat=c.cliff_beat,
                  repaired=bool(repairs), repairs=repairs)
    return promo, [f"{c.id}: repaired — {r}" for r in repairs]


def overlap(a: Promo, b: Promo) -> float:
    """Intersection over union of the two promos' time ranges."""
    inter = sum(max(0.0, min(sa.end, sb.end) - max(sa.start, sb.start))
                for sa in a.segments for sb in b.segments if sa.ep == sb.ep)
    union = a.duration + b.duration - inter
    return inter / union if union > 0 else 0.0


def dedupe(promos: list[Promo], iou: float = DEDUPE_IOU) -> list[Promo]:
    """Drop promos that mostly repeat an earlier one (list order = priority)."""
    kept: list[Promo] = []
    for p in promos:
        if all(overlap(p, k) <= iou for k in kept):
            kept.append(p)
    return kept
