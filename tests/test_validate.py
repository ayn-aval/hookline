from hookline.schemas import Beat, Candidate, Promo, Segment, SegmentRef
from hookline.validate import dedupe, validate_candidate


def B(i, start, end, kind="CAMERA", ep=1):
    return Beat(id=f"E{ep:02d}-B{i:03d}", ep=ep, scene=1, kind=kind, start=start, end=end, text=f"beat {i}")


def index(*beats):
    return {b.id: b for b in beats}


# A 70-second episode: beat every 5 s, plus a long dialogue line 38-44 s.
BASE = [B(i, (i - 1) * 5.0, i * 5.0) for i in range(1, 15)]
DLG = B(50, 38.0, 44.0, kind="DIALOGUE")
IDX = index(*BASE, DLG)


def cand(start, end, hook, cliff, segs=None, kind="continuous"):
    segs = segs or [(start, end)]
    return Candidate(id="c1", kind=kind, segments=[SegmentRef(start_beat=s, end_beat=e) for s, e in segs],
                     hook_beat=hook, cliff_beat=cliff, hook="h", cliffhanger="c", why="w")


def test_valid_40s_passes_untouched():
    p, notes = validate_candidate(cand("E01-B002", "E01-B009", "E01-B002", "E01-B009"), IDX)
    assert p is not None, notes
    assert (p.segments[0].start, p.segments[0].end) == (5.0, 45.0)
    assert p.duration == 40.0
    assert not p.repaired


def test_snap_extends_over_dialogue():
    # end beat B008 ends at 40.0, but the dialogue line runs 38-44 -> must extend to 44.0
    p, notes = validate_candidate(cand("E01-B002", "E01-B008", "E01-B002", "E01-B008"), IDX)
    assert p is not None, notes
    assert p.segments[0].end == 44.0
    assert p.repaired


def test_validate_rejects_unknown_beat():
    p, notes = validate_candidate(cand("E01-B002", "E01-B999", "E01-B002", "E01-B999"), IDX)
    assert p is None
    assert any("unknown" in n for n in notes)


def test_validate_rejects_reversed_segment():
    p, notes = validate_candidate(cand("E01-B009", "E01-B002", "E01-B009", "E01-B002"), IDX)
    assert p is None
    assert any("reversed" in n for n in notes)


def test_validate_duration_bounds():
    short, notes = validate_candidate(cand("E01-B002", "E01-B004", "E01-B002", "E01-B004"), IDX)  # 15 s
    assert short is None and any("short" in n for n in notes)
    # 65 s with hook at the very start -> cannot trim -> rejected
    long_, notes = validate_candidate(cand("E01-B001", "E01-B013", "E01-B001", "E01-B013"), IDX)
    assert long_ is None and any("long" in n for n in notes)


def test_hook_within_3s():
    # hook beat B003 starts 10 s after promo start -> start moves to hook (duration stays >= 20)
    p, notes = validate_candidate(cand("E01-B001", "E01-B009", "E01-B003", "E01-B009"), IDX)
    assert p is not None, notes
    assert p.segments[0].start == 10.0
    assert p.repaired and any("hook" in r for r in p.repairs)


def test_long_promo_trimmed_to_hook():
    # 65 s, hook at 10 s -> trimmed to start at hook -> 55 s passes
    p, notes = validate_candidate(cand("E01-B001", "E01-B013", "E01-B003", "E01-B013"), IDX)
    assert p is not None, notes
    assert p.duration == 55.0


def test_cliff_at_end():
    # cliff beat B007 ends at 35 but segment ends at 50 -> end trimmed to 35
    p, notes = validate_candidate(cand("E01-B002", "E01-B010", "E01-B002", "E01-B007"), IDX)
    assert p is not None, notes
    assert p.segments[-1].end == 35.0
    # cliff in an episode not in the last segment -> rejected
    p2, notes2 = validate_candidate(cand("E01-B002", "E01-B010", "E01-B002", "E02-B001"), {**IDX, "E02-B001": B(1, 0, 3, ep=2)})
    assert p2 is None


def test_stitched_cross_episode_cold_open():
    ep2 = [B(i, (i - 1) * 5.0, i * 5.0, ep=2) for i in range(1, 6)]
    idx = {**IDX, **index(*ep2)}
    c = cand(None, None, "E02-B002", "E01-B006", segs=[("E02-B002", "E02-B003"), ("E01-B003", "E01-B006")],
             kind="stitched")
    p, notes = validate_candidate(c, idx)
    assert p is not None, notes
    assert [s.ep for s in p.segments] == [2, 1]
    assert p.duration == 10.0 + 20.0


def test_stitched_overlapping_segments_rejected():
    c = cand(None, None, "E01-B002", "E01-B006", segs=[("E01-B002", "E01-B005"), ("E01-B004", "E01-B006")],
             kind="stitched")
    p, notes = validate_candidate(c, IDX)
    assert p is None and any("overlap" in n for n in notes)


def P(pid, ep, start, end):
    return Promo(id=pid, kind="continuous", segments=[Segment(ep=ep, start=start, end=end, start_beat="x", end_beat="y")],
                 duration=end - start, hook_beat="x", cliff_beat="y")


def test_dedupe_iou():
    keep = dedupe([P("a", 1, 0, 40), P("b", 1, 5, 42), P("c", 1, 50, 90), P("d", 2, 0, 40)])
    assert [p.id for p in keep] == ["a", "c", "d"]
