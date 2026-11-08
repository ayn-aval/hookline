"""Spoiler risk, decided in code from the bible's reveal list (0 = none, 1 = late-series, 2 = gives away a twist)."""
from __future__ import annotations

from ..render import promo_text
from ..schemas import ParseResult, Promo

LATE_SERIES_FRACTION = 0.8
MIN_EPISODES_FOR_LATE_RULE = 5


def spoiler_level(p: Promo, show: ParseResult, bible: dict) -> int:
    text = promo_text(p, show).lower()
    last_ep = max(p.episodes)
    for reveal in bible.get("reveals") or []:
        if not isinstance(reveal, dict) or reveal.get("ad_safe", True):
            continue
        try:
            reveal_ep = int(reveal.get("episode") or 0)
        except (TypeError, ValueError):
            continue
        keywords = [str(k).lower() for k in reveal.get("keywords") or [] if str(k).strip()]
        if last_ep >= reveal_ep and any(k in text for k in keywords):
            return 2
    final_ep = max(e.num for e in show.episodes)
    if len(show.episodes) >= MIN_EPISODES_FOR_LATE_RULE and min(p.episodes) > LATE_SERIES_FRACTION * final_ep:
        return 1
    return 0
