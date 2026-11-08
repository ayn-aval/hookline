"""Turn judged promos into a posting order using transparent, tunable weights (see rules.py)."""
from __future__ import annotations

from .rules import (DIVERSITY_WINDOW, FUNNEL_PENALTY, JUDGE_WEIGHTS, SPOILER_PENALTY, SWEET_SPOT,
                    SWEET_SPOT_BONUS)
from .schemas import Promo

REASON_LABELS = {
    "hook": "scroll-stopping hook",
    "cliff": "strong cliffhanger",
    "standalone": "clear to a first-time viewer",
    "emotion": "high emotional pull",
}


def _judged(p: Promo) -> bool:
    return p.scores.get("judged", True) is not False


def score_promo(p: Promo, n_episodes: int) -> float:
    judge = sum(w * float(p.scores.get(k) or 0) for k, w in JUDGE_WEIGHTS.items())
    bonus = SWEET_SPOT_BONUS if SWEET_SPOT[0] <= p.duration <= SWEET_SPOT[1] else 0.0
    funnel = FUNNEL_PENALTY * (min(p.episodes) - 1) / max(1, n_episodes - 1)
    return round(judge + bonus - SPOILER_PENALTY * p.spoiler - funnel, 3)


def _reason(p: Promo, n_episodes: int) -> str:
    if not _judged(p):
        return "not scored by the judge; review manually"
    best = max(JUDGE_WEIGHTS, key=lambda k: float(p.scores.get(k) or 0))
    parts = [f"{REASON_LABELS[best]} ({p.scores.get(best)}/5)"]
    first_ep = min(p.episodes)
    if first_ep <= max(3, n_episodes // 10):
        parts.append(f"starts in Ep {first_ep}, so a new viewer who clicks reaches the payoff quickly")
    if p.spoiler:
        parts.append("some spoiler risk, so held back")
    if SWEET_SPOT[0] <= p.duration <= SWEET_SPOT[1]:
        parts.append(f"{p.duration:.0f}s is in the 30-45s sweet spot")
    return "; ".join(parts)


def rank_promos(promos: list[Promo], n_episodes: int) -> list[Promo]:
    """Best score first; avoid two promos from the same episode back to back when a close alternative exists.

    Unjudged promos go last so a judge failure never masquerades as a weak promo.
    """
    for p in promos:
        p.final_score = score_promo(p, n_episodes)
    pool = sorted((p for p in promos if _judged(p)), key=lambda p: -p.final_score)
    order: list[Promo] = []
    while pool:
        pick = pool[0]
        if order and min(pick.episodes) == min(order[-1].episodes):
            pick = next((q for q in pool[1:] if min(q.episodes) != min(order[-1].episodes)
                         and pick.final_score - q.final_score <= DIVERSITY_WINDOW), pick)
        pool.remove(pick)
        order.append(pick)
    order += [p for p in promos if not _judged(p)]
    for i, p in enumerate(order, 1):
        p.rank = i
        p.post_reason = _reason(p, n_episodes)
    return order
