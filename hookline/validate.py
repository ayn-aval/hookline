"""Turn LLM candidates (beat IDs) into promos with real, checked timestamps.

This is where the promo rules are enforced in code, not trusted to the model:
  * every timestamp comes from a real beat (unknown IDs are rejected)
  * no cut lands in the middle of a spoken line
  * the hook starts within 3 s of the promo start
  * the promo ends on the cliffhanger beat
  * total length is 20-60 s
"""
from __future__ import annotations

from collections import defaultdict

from .rules import CLIFF_TOLERANCE, DEDUPE_IOU, HOOK_WINDOW, MAX_DURATION, MIN_DURATION
from .schemas import Beat, Candidate, Promo, Segment


def dialogue_by_episode(index: dict[str, Beat]) -> dict[int, list[Beat]]:
    by_ep: dict[int, list[Beat]] = defaultdict(list)
    for b in index.values():
        if b.kind == "DIALOGUE":
            by_ep[b.ep].append(b)
    return by_ep


def _snap(ep_dialogue: list[Beat], start: float, end: float) -> tuple[float, float]:
    """Widen [start, end] so no spoken line is cut mid-way (repeat until stable)."""
    changed = True
    while changed:
        changed = False
        for d in ep_dialogue:
            if d.start < start < d.end:
                start, changed = d.start, True
            if d.start < end < d.end:
                end, changed = d.end, True
    return round(start, 2), round(end, 2)


def validate_candidate(c: Candidate, index: dict[str, Beat],
                       dialogue_by_ep: dict[int, list[Beat]] | None = None) -> tuple[Promo | None, list[str]]:
    """Return (promo, notes). promo is None if the candidate cannot be made valid; notes say why."""
    notes: list[str] = []
    repairs: list[str] = []
    dialogue_by_ep = dialogue_by_ep if dialogue_by_ep is not None else dialogue_by_episode(index)

    ids = [x for s in c.segments for x in (s.start_beat, s.end_beat)] + [c.hook_beat, c.cliff_beat]
    unknown = [i for i in ids if i not in index]
    if unknown:
        return None, [f"{c.id}: unknown beat id(s) {sorted(set(unknown))}"]
    if not c.segments:
        return None, [f"{c.id}: no segments"]

    spans: list[list] = []  # [ep, start, end, start_beat, end_beat]
    for s in c.segments:
        a, b = index[s.start_beat], index[s.end_beat]
        if a.ep != b.ep:
            return None, [f"{c.id}: segment {s.start_beat}->{s.end_beat} spans two episodes"]
        if b.start < a.start:
            return None, [f"{c.id}: reversed segment {s.start_beat}->{s.end_beat}"]
        spans.append([a.ep, a.start, max(a.end, b.end), a.id, b.id])

    # hook: must be in the first segment's episode; promo must open on it (within 3 s)
    hook = index[c.hook_beat]
    first = spans[0]
    if hook.ep != first[0] or hook.start > first[2]:
        return None, [f"{c.id}: hook beat {c.hook_beat} is not inside the first segment"]
    if hook.start - first[1] > HOOK_WINDOW or hook.start < first[1]:
        repairs.append(f"start moved {first[1]:.1f}s -> {hook.start:.1f}s to open on the hook")
        first[1] = hook.start

    # cliffhanger: must be in the last segment's episode; promo must end on it
    cliff = index[c.cliff_beat]
    last = spans[-1]
    if cliff.ep != last[0] or cliff.end < last[1]:
        return None, [f"{c.id}: cliffhanger beat {c.cliff_beat} is not inside the last segment"]
    if abs(last[2] - cliff.end) > CLIFF_TOLERANCE:
        repairs.append(f"end moved {last[2]:.1f}s -> {cliff.end:.1f}s to cut on the cliffhanger")
        last[2] = cliff.end

    # never cut mid-line
    for sp in spans:
        ns, ne = _snap(dialogue_by_ep.get(sp[0], []), sp[1], sp[2])
        if (ns, ne) != (round(sp[1], 2), round(sp[2], 2)):
            repairs.append(f"ep{sp[0]} cut widened to {ns:.1f}-{ne:.1f}s so no line is cut mid-sentence")
        sp[1], sp[2] = ns, ne
        if sp[2] <= sp[1]:
            return None, [f"{c.id}: empty segment after repairs"]

    if hook.start - spans[0][1] > HOOK_WINDOW:
        return None, [f"{c.id}: hook lands {hook.start - spans[0][1]:.1f}s in (>3s) even after repair"]

    # segments of the same episode must not overlap
    for i in range(len(spans)):
        for j in range(i + 1, len(spans)):
            if spans[i][0] == spans[j][0] and spans[i][1] < spans[j][2] and spans[j][1] < spans[i][2]:
                return None, [f"{c.id}: segments {i + 1} and {j + 1} overlap in ep{spans[i][0]}"]

    total = round(sum(sp[2] - sp[1] for sp in spans), 2)
    if total < MIN_DURATION:
        return None, [f"{c.id}: too short ({total:.1f}s < {MIN_DURATION:.0f}s)"]
    if total > MAX_DURATION:
        return None, [f"{c.id}: too long ({total:.1f}s > {MAX_DURATION:.0f}s)"]

    promo = Promo(
        id=c.id, kind=c.kind, title=c.title,
        segments=[Segment(ep=sp[0], start=sp[1], end=sp[2], start_beat=sp[3], end_beat=sp[4]) for sp in spans],
        duration=total, hook=c.hook, cliffhanger=c.cliffhanger, why=c.why,
        hook_beat=c.hook_beat, cliff_beat=c.cliff_beat, repaired=bool(repairs), repairs=repairs,
    )
    return promo, notes + [f"{c.id}: repaired — {r}" for r in repairs]


def overlap(a: Promo, b: Promo) -> float:
    inter = 0.0
    for sa in a.segments:
        for sb in b.segments:
            if sa.ep == sb.ep:
                inter += max(0.0, min(sa.end, sb.end) - max(sa.start, sb.start))
    union = a.duration + b.duration - inter
    return inter / union if union > 0 else 0.0


def dedupe(promos: list[Promo], iou: float = DEDUPE_IOU) -> list[Promo]:
    """Drop promos that mostly repeat an earlier one (list order = priority)."""
    kept: list[Promo] = []
    for p in promos:
        if all(overlap(p, k) <= iou for k in kept):
            kept.append(p)
    return kept
