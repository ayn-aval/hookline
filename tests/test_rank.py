from hookline.rank import rank_promos, score_promo
from hookline.schemas import Promo, Segment


def P(pid, ep, judge=4, dur=40.0, spoiler=0):
    return Promo(id=pid, kind="continuous",
                 segments=[Segment(ep=ep, start=0, end=dur, start_beat="x", end_beat="y")],
                 duration=dur, hook_beat="x", cliff_beat="y", spoiler=spoiler,
                 scores={"hook": judge, "cliff": judge, "standalone": judge, "emotion": judge})


def test_rank_orders_by_score_with_funnel_and_diversity():
    ranked = rank_promos([P("late", 40), P("early", 2), P("early2", 2), P("mid", 20)], n_episodes=50)
    ids = [p.id for p in ranked]
    assert ids[0] == "early"
    # the second ep-2 promo is not placed right after the first when an alternative is close
    assert ids[1] != "early2"
    assert [p.rank for p in ranked] == [1, 2, 3, 4]
    assert all(p.post_reason for p in ranked)


def test_spoiler_penalised():
    assert score_promo(P("a", 5, spoiler=2), 50) < score_promo(P("b", 5, spoiler=0), 50)


def test_duration_sweet_spot_bonus():
    assert score_promo(P("a", 5, dur=38), 50) > score_promo(P("b", 5, dur=58), 50)


def test_stronger_judge_scores_win_over_funnel():
    ranked = rank_promos([P("weak-early", 1, judge=2), P("strong-late", 30, judge=5)], n_episodes=50)
    assert ranked[0].id == "strong-late"
