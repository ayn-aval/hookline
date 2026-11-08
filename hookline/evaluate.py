"""Quality checks for a finished run.

1. Baseline: the same blind judge scores a naive "last 45 s of each episode" cut.
2. Stability: a second model (or temperature) re-mines the episodes; how many of the
   top-10 continuous promos does it find again?
3. Constraints: how many model proposals passed, were repaired, or were rejected.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from statistics import mean
from typing import Optional

from .baseline import baseline_promos
from .report import load_run
from .rules import JUDGE_WEIGHTS
from .schemas import ParseResult, Promo
from .pipeline import DEFAULT_EPISODES_PER_CALL
from .stages import judge_promos, mine_episodes, mined_candidates
from .validate import dedupe, dialogue_by_episode, overlap, validate_candidate

TOP_N = 15
STABILITY_TOP = 10
STABILITY_IOU = 0.5
SCORE_KEYS = ("hook", "cliff", "standalone", "emotion")


def weighted(p: Promo) -> float:
    return sum(w * float(p.scores.get(k) or 0) for k, w in JUDGE_WEIGHTS.items())


def score_summary(promos: list[Promo]) -> dict:
    judged = [p for p in promos if p.scores.get("judged", True) is not False]
    if not judged:
        return {"n": 0, "mean": {}}
    means = {k: round(mean(float(p.scores.get(k) or 0) for p in judged), 2) for k in SCORE_KEYS}
    means["weighted"] = round(mean(weighted(p) for p in judged), 2)
    return {"n": len(judged), "mean": means}


def top_overlap(main: list[Promo], alt: list[Promo], iou: float = STABILITY_IOU) -> float:
    """Share of `main` promos that `alt` re-found (time overlap above `iou`)."""
    if not main:
        return 0.0
    found = sum(any(overlap(m, a) > iou for a in alt) for m in main)
    return round(found / len(main), 3)


def remine(show: ParseResult, bible: dict, llm, episodes: Optional[list[int]], workers: int,
           episodes_per_call: int = DEFAULT_EPISODES_PER_CALL) -> list[Promo]:
    selected = [e for e in show.episodes if not episodes or e.num in set(episodes)]
    batches = [selected[i:i + episodes_per_call] for i in range(0, len(selected), episodes_per_call)]
    index = show.beat_index()
    dialogue = dialogue_by_episode(index)

    def mine(batch) -> list[Promo]:
        try:
            mined = mine_episodes(batch, bible, llm)
        except Exception:  # noqa: BLE001 - a failed batch simply contributes nothing
            return []
        promos = [validate_candidate(c, index, dialogue)[0]
                  for n, raw in mined.items() for c in mined_candidates(n, raw)]
        return [p for p in promos if p]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dedupe([p for found in pool.map(mine, batches) for p in found])


def _markdown(results: dict) -> str:
    b, h, t = results["baseline"], results["hookline_all"], results["hookline_top"]
    rows = ["| | n | hook | cliff | standalone | emotion | weighted |", "|---|---|---|---|---|---|---|"]
    for name, s in [("Baseline: last 45 s of each episode", b), ("Hookline: all promos", h),
                    (f"Hookline: top {TOP_N}", t)]:
        m = s["mean"]
        rows.append(f"| {name} | {s['n']} | " + " | ".join(str(m.get(k, "-")) for k in
                                                          (*SCORE_KEYS, "weighted")) + " |")
    st, c = results["stability"], results["constraints"]
    lines = ["# Evaluation results", "", "## Blind cold-viewer judge scores (1-5)", "", *rows, ""]
    if st:
        lines += ["## Stability", "",
                  f"A second pass with `{st['alt_model']}` re-mined {st['episodes']} episodes and re-found "
                  f"**{st['top10_refound']:.0%}** of the top-{STABILITY_TOP} continuous promos "
                  f"(time overlap > {STABILITY_IOU:.0%}).", ""]
    lines += ["## Constraint checks", "",
              f"Proposed {c.get('proposed')} · valid {c.get('valid')} · auto-repaired {c.get('repaired')} · "
              f"rejected {c.get('rejected')} · duplicates removed {c.get('duplicates_removed')} · "
              f"final {c.get('final')} · unjudged {c.get('unjudged', 0)}", ""]
    return "\n".join(lines)


def evaluate(out_dir: Path, show: ParseResult, llm, alt_llm=None, judge_llm=None, eval_dir: Optional[Path] = None,
             workers: int = 4, stability_episodes: Optional[list[int]] = None,
             episodes_per_call: int = DEFAULT_EPISODES_PER_CALL) -> dict:
    """`llm` judges the baseline (pass the run's judge model); `alt_llm` re-mines for stability."""
    out_dir = Path(out_dir)
    eval_dir = Path(eval_dir) if eval_dir else out_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    promos, bible, meta = load_run(out_dir)

    baseline = baseline_promos(show)
    judge_promos(baseline, show, judge_llm or llm, tag_prefix="05_baseline_judge", max_workers=workers)
    ranked = sorted(promos, key=lambda p: p.rank or 10**6)

    stability = {}
    if alt_llm is not None:
        alt = remine(show, bible, alt_llm, stability_episodes, workers, episodes_per_call)
        main_top = [p for p in ranked if p.kind == "continuous"][:STABILITY_TOP]
        stability = {"alt_model": f"{alt_llm.cfg.model} (temperature {alt_llm.cfg.temperature})",
                     "episodes": len(stability_episodes or show.episodes),
                     "alt_promos": len(alt), "top10_refound": top_overlap(main_top, alt)}

    results = {
        "baseline": score_summary(baseline),
        "baseline_promos": [{"id": p.id, "scores": p.scores} for p in baseline],
        "hookline_all": score_summary(promos),
        "hookline_top": score_summary(ranked[:TOP_N]),
        "stability": stability,
        "constraints": meta.get("candidates", {}),
        "judge_model": getattr((judge_llm or llm).cfg, "model", "?"),
        "llm_usage": dict((judge_llm or llm).usage),
    }
    (eval_dir / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    markdown = _markdown(results)
    (eval_dir / "results.md").write_text(markdown)
    b, t = results["baseline"]["mean"], results["hookline_top"]["mean"]
    summary = (f"Baseline weighted {b.get('weighted')} vs Hookline top-{TOP_N} {t.get('weighted')}; "
               f"stability {stability.get('top10_refound', 'n/a')}")
    return {**results, "summary": summary, "markdown": markdown}
