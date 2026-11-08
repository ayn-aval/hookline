"""Stage 2: per-episode mining of continuous promo windows and standout moments."""
from __future__ import annotations

from ..prompts import load_prompt
from ..render import episode_block
from ..schemas import Candidate, Episode, SegmentRef
from .bible import bible_text


def mine_episode(ep: Episode, bible: dict, llm) -> dict:
    user = f"SERIES BIBLE:\n{bible_text(bible)}\n\nSCREENPLAY:\n{episode_block(ep)}"
    out = llm.json(load_prompt("mine_episode"), user, tag=f"02_mine_ep{ep.num:02d}")
    return out if isinstance(out, dict) else {"candidates": [], "moments": []}


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
