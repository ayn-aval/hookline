"""Orchestrates a run: parse result -> bible -> mine -> stitch -> validate -> judge -> rank."""
from __future__ import annotations

import time
from typing import Callable, Optional

from .llm import JSONModel
from .prompts import prompts_sha
from .rank import rank_promos
from .rules import PRICE_PER_M_INPUT, PRICE_PER_M_OUTPUT
from .schemas import Candidate, ParseResult, Promo, RunResult
from .stages import judge_promos, make_bible, mine_all, mined_candidates, spoiler_level, stitch
from .validate import beats_by_episode, dedupe, dialogue_by_episode, validate_candidate

Progress = Optional[Callable[[str, float], None]]
DEFAULT_EPISODES_PER_CALL = 5


def validate_all(candidates: list[Candidate], show: ParseResult) -> tuple[list[Promo], list[str]]:
    """Valid promos (in candidate order) and the reasons the others were rejected."""
    index = show.beat_index()
    dialogue, ep_beats = dialogue_by_episode(index), beats_by_episode(index)
    valid, rejections = [], []
    for c in candidates:
        promo, notes = validate_candidate(c, index, dialogue, ep_beats)
        if promo is None:
            rejections.extend(notes)
        else:
            valid.append(promo)
    return valid, rejections


def _usable_episodes(show: ParseResult, episodes: Optional[list[int]]) -> ParseResult:
    wanted = set(episodes) if episodes else None
    selected = [e for e in show.episodes if wanted is None or e.num in wanted]
    kept = [e for e in selected if e.beats]
    warnings = show.warnings + [f"ep{e.num}: skipped, no beats parsed" for e in selected if not e.beats]
    if not kept:
        raise ValueError("no episodes with parseable beats to process")
    return ParseResult(episodes=kept, warnings=warnings)


def _combined_usage(llm: JSONModel, judge_llm: JSONModel) -> dict:
    usage = dict(llm.usage)
    if judge_llm is not llm:
        for k, v in judge_llm.usage.items():
            usage[k] = usage.get(k, 0) + v
    return usage


def run_pipeline(show: ParseResult, llm: JSONModel, judge_llm: Optional[JSONModel] = None,
                 progress: Progress = None, max_workers: int = 4, episodes: Optional[list[int]] = None,
                 episodes_per_call: int = DEFAULT_EPISODES_PER_CALL) -> RunResult:
    """Run every stage. `judge_llm` defaults to `llm`; a different model avoids grading its own picks."""
    started = time.time()
    say = progress or (lambda message, fraction: None)
    judge_llm = judge_llm or llm
    show = _usable_episodes(show, episodes)
    total_eps = len(show.episodes)

    say("Building series bible", 0.02)
    bible = make_bible(show, llm)
    mined = mine_all(show.episodes, bible, llm, episodes_per_call, max_workers,
                     on_batch=lambda done: say(f"Mined {done}/{total_eps} episodes", 0.05 + 0.6 * done / total_eps))
    errors = {f"ep{n}": m["error"] for n, m in sorted(mined.items()) if m.get("error")}

    candidates, rejections = [], []
    for n in sorted(mined):
        found, notes = mined_candidates(n, mined[n])
        candidates += found
        rejections += notes
    say("Stitching multi-moment promos", 0.68)
    try:
        stitched, notes = stitch(show, bible, mined, llm)
        candidates += stitched
        rejections += notes
    except Exception as exc:  # noqa: BLE001 - continuous promos are still useful without stitching
        errors["stitch"] = str(exc)[:300]

    valid, validation_notes = validate_all(candidates, show)
    rejections += validation_notes
    unique = dedupe(valid)

    say("Judging promos as a cold viewer", 0.72)
    judge_errors = judge_promos(unique, show, judge_llm, max_workers=max_workers,
                                progress=lambda m, f: say(m, 0.72 + 0.25 * f))
    errors.update({f"judge{i + 1}": e for i, e in enumerate(judge_errors)})
    for p in unique:
        p.spoiler = spoiler_level(p, show, bible)
    ranked = rank_promos(unique, n_episodes=max(e.num for e in show.episodes))

    usage = _combined_usage(llm, judge_llm)
    meta = {
        "show_episodes": [e.num for e in show.episodes],
        "provider": llm.cfg.provider,
        "model": llm.cfg.model,
        "judge_model": judge_llm.cfg.model,
        "episodes_per_call": episodes_per_call,
        "temperature": llm.cfg.temperature,
        "prompts_sha": prompts_sha(),
        "candidates": {
            "proposed": len(candidates),
            "continuous_proposed": sum(c.kind == "continuous" for c in candidates),
            "stitched_proposed": sum(c.kind == "stitched" for c in candidates),
            "valid": len(valid),
            "repaired": sum(p.repaired for p in valid),
            "rejected": len(candidates) - len(valid),
            "duplicates_removed": len(valid) - len(unique),
            "final": len(ranked),
            "unjudged": sum(not p.judged for p in ranked),
        },
        "rejections": rejections,
        "errors": errors,
        "llm_usage": usage,
        "est_cost_usd_paid_tier": round(usage.get("prompt_tokens", 0) / 1e6 * PRICE_PER_M_INPUT
                                        + usage.get("completion_tokens", 0) / 1e6 * PRICE_PER_M_OUTPUT, 4),
        "price_assumption_per_1m_tokens": {"input": PRICE_PER_M_INPUT, "output": PRICE_PER_M_OUTPUT},
        "seconds": round(time.time() - started, 1),
        "parse_warnings": show.warnings,
    }
    say("Done", 1.0)
    return RunResult(promos=ranked, bible=bible, meta=meta)
