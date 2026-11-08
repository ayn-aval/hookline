"""Stage 2: mining continuous promo windows and standout moments, a few episodes per call.

Several episodes per call keeps a full show inside free-tier request quotas; set
episodes_per_call=1 on a paid tier for the model's undivided attention per episode.
"""
from __future__ import annotations

from ..prompts import load_prompt
from ..render import episode_block
from ..schemas import Candidate, Episode, SegmentRef
from .bible import bible_text


def batch_tag(episodes: list[Episode]) -> str:
    return f"02_mine_eps{episodes[0].num:02d}-{episodes[-1].num:02d}"


def mine_episodes(episodes: list[Episode], bible: dict, llm) -> dict[int, dict]:
    """Return {episode number: {"candidates": [...], "moments": [...]}} for every episode in the batch."""
    screenplays = "\n\n".join(episode_block(ep) for ep in episodes)
    user = f"SERIES BIBLE:\n{bible_text(bible)}\n\nSCREENPLAYS:\n{screenplays}"
    out = llm.json(load_prompt("mine_episode"), user, tag=batch_tag(episodes))
    rows = out.get("episodes") if isinstance(out, dict) else None
    by_ep: dict[int, dict] = {}
    for row in rows or []:
        try:
            by_ep[int(row.get("episode"))] = row
        except (AttributeError, TypeError, ValueError):
            continue
    return {ep.num: by_ep.get(ep.num, {"candidates": [], "moments": []}) for ep in episodes}


def mined_candidates(ep_num: int, mined: dict) -> list[Candidate]:
    """Convert the model's proposals into Candidates, skipping malformed entries."""
    candidates = []
    for i, c in enumerate(mined.get("candidates") or [], 1):
        try:
            candidates.append(Candidate(
                id=f"E{ep_num:02d}-C{i}", kind="continuous", title=str(c.get("title", "")),
                segments=[SegmentRef(start_beat=str(c["start_beat"]), end_beat=str(c["end_beat"]))],
                hook_beat=str(c.get("hook_beat") or c["start_beat"]),
                cliff_beat=str(c.get("cliff_beat") or c["end_beat"]),
                hook=str(c.get("hook", "")), cliffhanger=str(c.get("cliffhanger", "")),
                why=str(c.get("why", "")), context_needed=str(c.get("context_needed") or "")))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
    return candidates
