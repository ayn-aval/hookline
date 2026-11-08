"""Orchestrates a run: parse result -> bible -> mine -> stitch -> validate -> judge -> rank."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from .prompts import prompts_sha
from .rank import rank_promos
from .rules import PRICE_PER_M_INPUT, PRICE_PER_M_OUTPUT
from .schemas import Candidate, ParseResult, Promo
from .stages import judge_promos, make_bible, mine_episode, mined_candidates, spoiler_level, stitch
from .validate import dedupe, dialogue_by_episode, validate_candidate

Progress = Optional[Callable[[str, float], None]]


@dataclass
class RunResult:
    promos: list[Promo]
    bible: dict
    meta: dict = field(default_factory=dict)


def _mine_all(show: ParseResult, bible: dict, llm, max_workers: int, say) -> dict[int, dict]:
    mined: dict[int, dict] = {}
    total = len(show.episodes)

    def mine(ep) -> None:
        try:
            mined[ep.num] = mine_episode(ep, bible, llm)
        except Exception as exc:  # noqa: BLE001 - one failed episode must not stop the run
            mined[ep.num] = {"candidates": [], "moments": [], "error": str(exc)[:300]}
        say(f"Mined {len(mined)}/{total} episodes", 0.05 + 0.6 * len(mined) / total)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(mine, show.episodes))
    return mined


def _validate_all(candidates: list[Candidate], show: ParseResult) -> tuple[list[Promo], list[str], int]:
    index = show.beat_index()
    dialogue = dialogue_by_episode(index)
    valid, rejections, repaired = [], [], 0
    for c in candidates:
        promo, notes = validate_candidate(c, index, dialogue)
        if promo is None:
            rejections.extend(notes)
        else:
            valid.append(promo)
            repaired += int(promo.repaired)
    return valid, rejections, repaired


def run_pipeline(show: ParseResult, llm, progress: Progress = None, max_workers: int = 4,
                 episodes: Optional[list[int]] = None) -> RunResult:
    started = time.time()
    say = progress or (lambda message, fraction: None)
    if episodes:
        wanted = set(episodes)
        show = ParseResult(episodes=[e for e in show.episodes if e.num in wanted], warnings=show.warnings)
    if not show.episodes:
        raise ValueError("no episodes to process")

    say("Building series bible", 0.02)
    bible = make_bible(show, llm)
    mined = _mine_all(show, bible, llm, max_workers, say)

    candidates = [c for n in sorted(mined) for c in mined_candidates(n, mined[n])]
    say("Stitching multi-moment promos", 0.68)
    stitch_error = None
    try:
        candidates += stitch(show, bible, mined, llm)
    except Exception as exc:  # noqa: BLE001 - continuous promos are still useful without stitching
        stitch_error = str(exc)[:300]

    valid, rejections, repaired = _validate_all(candidates, show)
    unique = dedupe(valid)

    say("Judging promos as a cold viewer", 0.72)
    judge_promos(unique, show, llm, max_workers=max_workers, progress=lambda m, f: say(m, 0.72 + 0.25 * f))
    for p in unique:
        p.spoiler = spoiler_level(p, show, bible)
    ranked = rank_promos(unique, n_episodes=max(e.num for e in show.episodes))

    usage = dict(llm.usage)
    meta = {
        "show_episodes": [e.num for e in show.episodes],
        "provider": getattr(llm.cfg, "provider", "?"),
        "model": getattr(llm.cfg, "model", "?"),
        "temperature": getattr(llm.cfg, "temperature", None),
        "prompts_sha": prompts_sha(),
        "candidates": {
            "proposed": len(candidates),
            "continuous_proposed": sum(c.kind == "continuous" for c in candidates),
            "stitched_proposed": sum(c.kind == "stitched" for c in candidates),
            "valid": len(valid), "repaired": repaired, "rejected": len(candidates) - len(valid),
            "duplicates_removed": len(valid) - len(unique), "final": len(ranked),
            "unjudged": sum(not p.scores.get("judged") for p in ranked),
        },
        "rejections": rejections,
        "errors": {**{f"ep{n}": m["error"] for n, m in mined.items() if m.get("error")},
                   **({"stitch": stitch_error} if stitch_error else {})},
        "llm_usage": usage,
        "est_cost_usd_paid_tier": round(usage.get("prompt_tokens", 0) / 1e6 * PRICE_PER_M_INPUT
                                        + usage.get("completion_tokens", 0) / 1e6 * PRICE_PER_M_OUTPUT, 4),
        "price_assumption_per_1m_tokens": {"input": PRICE_PER_M_INPUT, "output": PRICE_PER_M_OUTPUT},
        "seconds": round(time.time() - started, 1),
        "parse_warnings": show.warnings,
    }
    say("Done", 1.0)
    return RunResult(promos=ranked, bible=bible, meta=meta)
