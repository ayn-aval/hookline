"""Rank judged promos into a posting order (pure code, transparent weights)."""
from __future__ import annotations

from .schemas import Promo

WEIGHTS = {"hook": 0.30, "cliff": 0.25, "standalone": 0.25, "emotion": 0.20}
SWEET_SPOT = (30.0, 45.0)
SWEET_BONUS = 0.3
SPOILER_PENALTY = 0.6
FUNNEL_PENALTY = 0.4  # max penalty for a promo whose earliest moment is in the last episode
DIVERSITY_WINDOW = 0.25


def score_promo(p: Promo, n_episodes: int) -> float:
    judge = sum(w * float(p.scores.get(k, 0) or 0) for k, w in WEIGHTS.items())
    bonus = SWEET_BONUS if SWEET_SPOT[0] <= p.duration <= SWEET_SPOT[1] else 0.0
    funnel = FUNNEL_PENALTY * (min(p.episodes) - 1) / max(1, n_episodes - 1)
    return round(judge + bonus - SPOILER_PENALTY * p.spoiler - funnel, 3)


def _reason(p: Promo, n_episodes: int) -> str:
    s = p.scores
    bits = []
    best = max(WEIGHTS, key=lambda k: float(s.get(k, 0) or 0))
    label = {"hook": "scroll-stopping hook", "cliff": "strong cliffhanger",
             "standalone": "clear to a first-time viewer", "emotion": "high emotional/trope pull"}[best]
    bits.append(f"{label} ({s.get(best, '?')}/5)")
    first_ep = min(p.episodes)
    if first_ep <= max(3, n_episodes // 10):
        bits.append(f"from Ep {first_ep}, so a new viewer who clicks lands right at the payoff")
    if p.spoiler:
        bits.append("some spoiler risk, so posted later")
    if SWEET_SPOT[0] <= p.duration <= SWEET_SPOT[1]:
        bits.append(f"{p.duration:.0f}s fits the 30-45s sweet spot")
    return "; ".join(bits)


def rank_promos(promos: list[Promo], n_episodes: int) -> list[Promo]:
    """Score every promo, then build a posting order: best first, avoiding back-to-back same episode."""
    for p in promos:
        p.final_score = score_promo(p, n_episodes)
    pool = sorted(promos, key=lambda p: -p.final_score)
    order: list[Promo] = []
    while pool:
        pick = pool[0]
        if order and min(pick.episodes) == min(order[-1].episodes):
            alt = next((q for q in pool[1:] if min(q.episodes) != min(order[-1].episodes)
                        and pick.final_score - q.final_score <= DIVERSITY_WINDOW), None)
            pick = alt or pick
        pool.remove(pick)
        order.append(pick)
    for i, p in enumerate(order, 1):
        p.rank = i
        p.post_reason = _reason(p, n_episodes)
    return order
