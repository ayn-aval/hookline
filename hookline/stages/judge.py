"""Stage 4: cold-viewer judge.

The judge sees only each clip's own text, never the series bible, so "makes sense on its own"
is tested rather than assumed. Clips the model skips are re-asked once; any still missing are
flagged as unjudged instead of silently scored zero.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..batching import chunked
from ..llm import JSONModel
from ..prompts import load_prompt
from ..render import clip_block
from ..rules import SCORE_KEYS
from ..schemas import ParseResult, Promo

BATCH_SIZE = 20
TEXT_KEYS = ("cold_viewer_summary", "weakness")


def _ask(batch: list[Promo], show: ParseResult, llm: JSONModel, tag: str) -> tuple[dict[str, dict], Optional[str]]:
    user = "\n\n".join(clip_block(p, show) for p in batch)
    try:
        out = llm.json(load_prompt("judge"), user, tag=tag)
    except Exception as exc:  # noqa: BLE001 - a failed batch is retried once, then reported
        return {}, f"{tag}: {str(exc)[:200]}"
    rows = out.get("scores") if isinstance(out, dict) else None
    return {str(r.get("id")): r for r in rows or [] if isinstance(r, dict)}, None


def _apply(p: Promo, row: dict) -> None:
    scores: dict = {"judged": True}
    for key in SCORE_KEYS:
        try:
            scores[key] = max(1, min(5, int(row.get(key))))
        except (TypeError, ValueError):
            scores[key] = 0
    scores.update({key: str(row.get(key) or "") for key in TEXT_KEYS})
    p.scores = scores


def judge_promos(promos: list[Promo], show: ParseResult, llm: JSONModel, tag_prefix: str = "04_judge",
                 max_workers: int = 4, progress: Optional[Callable[[str, float], None]] = None,
                 batch_size: int = BATCH_SIZE) -> list[str]:
    """Score promos in place; return the errors of batches that could not be judged."""
    batches = chunked(sorted(promos, key=lambda p: p.id), batch_size)
    errors: list[str] = []
    finished = [0]
    lock = threading.Lock()

    def run(numbered: tuple[int, list[Promo]]) -> None:
        k, batch = numbered
        rows, error = _ask(batch, show, llm, f"{tag_prefix}_{k:03d}")
        missing = [p for p in batch if p.id not in rows]
        if missing:
            retry_rows, retry_error = _ask(missing, show, llm, f"{tag_prefix}_{k:03d}_retry")
            rows.update(retry_rows)
            error = retry_error or error
        for p in batch:
            if p.id in rows:
                _apply(p, rows[p.id])
            else:
                p.scores = {"judged": False, **{key: 0 for key in SCORE_KEYS}, "weakness": "not scored by the judge"}
        with lock:
            if error and any(not p.judged for p in batch):
                errors.append(error)
            finished[0] += 1
            done = finished[0]
        if progress:
            progress(f"Judged {done}/{len(batches)} batches", done / max(1, len(batches)))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(run, enumerate(batches)))
    return errors
