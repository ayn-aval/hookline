"""Stage 4: cold-viewer judge.

The judge sees only each clip's own text, never the series bible, so "makes sense on its own"
is tested rather than assumed. Clips the model skips are re-asked once; any still missing are
flagged as unjudged instead of silently scored zero.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..prompts import load_prompt
from ..render import clip_block
from ..schemas import ParseResult, Promo

BATCH_SIZE = 20
SCORE_KEYS = ("hook", "cliff", "standalone", "emotion")
TEXT_KEYS = ("cold_viewer_summary", "weakness")


def _ask(batch: list[Promo], show: ParseResult, llm, tag: str) -> dict[str, dict]:
    user = "\n\n".join(clip_block(p, show) for p in batch)
    try:
        out = llm.json(load_prompt("judge"), user, tag=tag)
    except Exception:  # noqa: BLE001 - a failed batch is retried, then flagged
        return {}
    rows = (out or {}).get("scores") or [] if isinstance(out, dict) else []
    return {str(r.get("id")): r for r in rows if isinstance(r, dict)}


def _apply(p: Promo, row: dict) -> None:
    scores: dict = {"judged": True}
    for k in SCORE_KEYS:
        try:
            scores[k] = max(1, min(5, int(row.get(k))))
        except (TypeError, ValueError):
            scores[k] = 0
    scores.update({k: str(row.get(k) or "") for k in TEXT_KEYS})
    p.scores = scores


def judge_promos(promos: list[Promo], show: ParseResult, llm, tag_prefix: str = "04_judge",
                 max_workers: int = 4, progress: Optional[Callable[[str, float], None]] = None,
                 batch_size: int = BATCH_SIZE) -> None:
    ordered = sorted(promos, key=lambda p: p.id)
    batches = [ordered[i:i + batch_size] for i in range(0, len(ordered), batch_size)]
    finished = [0]

    def run(numbered: tuple[int, list[Promo]]) -> None:
        k, batch = numbered
        rows = _ask(batch, show, llm, f"{tag_prefix}_{k:03d}")
        missing = [p for p in batch if p.id not in rows]
        if missing:
            rows.update(_ask(missing, show, llm, f"{tag_prefix}_{k:03d}_retry"))
        for p in batch:
            if p.id in rows:
                _apply(p, rows[p.id])
            else:
                p.scores = {"judged": False, **{k2: 0 for k2 in SCORE_KEYS}, "weakness": "not scored by the judge"}
        finished[0] += 1
        if progress:
            progress(f"Judged {finished[0]}/{len(batches)} batches", finished[0] / max(1, len(batches)))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(run, enumerate(batches)))
