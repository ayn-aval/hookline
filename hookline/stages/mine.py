"""Stage 2: mining continuous promo windows and standout moments, a few episodes per call.

Several episodes per call keeps a full show inside free-tier request quotas; use
episodes_per_call=1 on a paid tier to give the model one episode at a time.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..batching import chunked
from ..llm import JSONModel
from ..prompts import load_prompt
from ..render import episode_block
from ..schemas import Candidate, Episode, SegmentRef
from .bible import bible_text

EMPTY = {"candidates": [], "moments": []}


def batch_tag(episodes: list[Episode]) -> str:
    return f"02_mine_eps{episodes[0].num:02d}-{episodes[-1].num:02d}"


def _ask(episodes: list[Episode], bible: dict, llm: JSONModel, tag: str) -> dict[int, dict]:
    screenplays = "\n\n".join(episode_block(ep) for ep in episodes)
    user = f"SERIES BIBLE:\n{bible_text(bible)}\n\nSCREENPLAYS:\n{screenplays}"
    out = llm.json(load_prompt("mine_episode"), user, tag=tag)
    rows = out.get("episodes") if isinstance(out, dict) else None
    by_ep: dict[int, dict] = {}
    for row in rows or []:
        try:
            by_ep[int(row.get("episode"))] = row
        except (AttributeError, TypeError, ValueError):
            continue
    return by_ep


def mine_episodes(episodes: list[Episode], bible: dict, llm: JSONModel) -> dict[int, dict]:
    """{episode number: {"candidates", "moments"[, "error"]}}; episodes the model skips are re-asked once."""
    tag = batch_tag(episodes)
    by_ep = _ask(episodes, bible, llm, tag)
    missing = [ep for ep in episodes if ep.num not in by_ep]
    if missing:
        by_ep.update(_ask(missing, bible, llm, f"{tag}_retry"))
    return {ep.num: by_ep.get(ep.num, {**EMPTY, "error": "omitted by the model twice"}) for ep in episodes}


def mine_all(episodes: list[Episode], bible: dict, llm: JSONModel, episodes_per_call: int, max_workers: int,
             on_batch: Optional[Callable[[int], None]] = None) -> dict[int, dict]:
    """Mine every episode in parallel batches; a failed batch records its error instead of stopping the run."""
    mined: dict[int, dict] = {}

    def mine(batch: list[Episode]) -> None:
        try:
            mined.update(mine_episodes(batch, bible, llm))
        except Exception as exc:  # noqa: BLE001 - one failed batch must not stop the run
            mined.update({ep.num: {**EMPTY, "error": str(exc)[:300]} for ep in batch})
        if on_batch:
            on_batch(len(mined))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(mine, chunked(episodes, episodes_per_call)))
    return mined


def mined_candidates(ep_num: int, mined: dict) -> tuple[list[Candidate], list[str]]:
    """The model's proposals as Candidates, plus a note for each malformed entry."""
    candidates, notes = [], []
    for i, c in enumerate(mined.get("candidates") or [], 1):
        cid = f"E{ep_num:02d}-C{i}"
        try:
            candidates.append(Candidate(
                id=cid, kind="continuous", title=str(c.get("title", "")),
                segments=[SegmentRef(start_beat=str(c["start_beat"]), end_beat=str(c["end_beat"]))],
                hook_beat=str(c.get("hook_beat") or c["start_beat"]),
                cliff_beat=str(c.get("cliff_beat") or c["end_beat"]),
                hook=str(c.get("hook", "")), cliffhanger=str(c.get("cliffhanger", "")),
                why=str(c.get("why", ""))))
        except (AttributeError, KeyError, TypeError, ValueError):
            notes.append(f"{cid}: malformed candidate from the model (missing beats)")
    return candidates, notes
