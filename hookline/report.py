"""Write run outputs: promos.json, promos.csv, report.md, run_meta.json, bible.json.

Committed outputs carry timestamps + short hook/cliffhanger quotes only, never the screenplay itself.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from .parse import fmt_ts
from .schemas import Promo, RunResult

CSV_COLS = ["rank", "promo_id", "kind", "title", "total_seconds", "segment", "episode", "start", "end",
            "segment_seconds", "hook", "cliffhanger", "why_it_works", "why_post_at_rank", "final_score",
            "hook_score", "cliff_score", "standalone_score", "emotion_score", "spoiler_risk", "repaired"]


def promo_dict(p: Promo) -> dict:
    d = p.model_dump()
    d["episodes"] = p.episodes
    for s in d["segments"]:
        s["start_ts"], s["end_ts"] = fmt_ts(s["start"]), fmt_ts(s["end"])
        s["seconds"] = round(s["end"] - s["start"], 2)
    return d


def promos_csv(promos: list[Promo]) -> str:
    """One row per segment, so an editor can cut directly from the sheet."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLS)
    for p in promos:
        for n, s in enumerate(p.segments, 1):
            writer.writerow([p.rank, p.id, p.kind, p.title, p.duration, n, s.ep, fmt_ts(s.start), fmt_ts(s.end),
                             round(s.end - s.start, 2), p.hook, p.cliffhanger, p.why, p.post_reason,
                             p.final_score, p.scores.get("hook"), p.scores.get("cliff"),
                             p.scores.get("standalone"), p.scores.get("emotion"), p.spoiler, p.repaired])
    return buffer.getvalue()


def promo_markdown(p: Promo) -> str:
    segs = "\n".join(f"  {n}. Ep {s.ep} · {fmt_ts(s.start)} → {fmt_ts(s.end)} ({s.end - s.start:.1f}s)"
                     for n, s in enumerate(p.segments, 1))
    sc = p.scores
    out = [f"### #{p.rank} — {p.title or p.id}  ·  {p.kind}, {p.duration:.1f}s  ·  score {p.final_score}",
           f"- **Segments (play order):**\n{segs}",
           f"- **Hook (first 3s):** {p.hook}",
           f"- **Cliffhanger:** {p.cliffhanger}",
           f"- **Why it works:** {p.why}",
           f"- **Why post at #{p.rank}:** {p.post_reason}",
           f"- **Cold-viewer judge:** hook {sc.get('hook')} · cliff {sc.get('cliff')} · standalone "
           f"{sc.get('standalone')} · emotion {sc.get('emotion')} · spoiler risk {p.spoiler}/2"
           + (f" — _\"{sc.get('cold_viewer_summary')}\"_" if sc.get("cold_viewer_summary") else "")
           + (f" — weakness: {sc.get('weakness')}" if sc.get("weakness") else ""),
           f"- id `{p.id}` · hook beat `{p.hook_beat}` · cliff beat `{p.cliff_beat}`"]
    if p.repairs:
        out.append("- _Auto-repairs:_ " + "; ".join(p.repairs))
    return "\n".join(out)


def report_markdown(promos: list[Promo], bible: dict, meta: dict, title: str = "Hookline promo report") -> str:
    c = meta.get("candidates", {})
    usage = meta.get("llm_usage", {})
    eps = meta.get("show_episodes") or []
    lines = [
        f"# {title}",
        "",
        f"**Show premise (from series bible):** {bible.get('show_premise', '')}",
        "",
        f"Episodes {min(eps) if eps else '?'}–{max(eps) if eps else '?'} · model "
        f"`{meta.get('provider')}/{meta.get('model')}`, judge `{meta.get('judge_model')}` · prompts "
        f"`{meta.get('prompts_sha')}` · LLM calls {usage.get('calls', 0) + usage.get('cached', 0)} "
        f"({usage.get('cached', 0)} served from cache)",
        "",
        f"Candidates proposed {c.get('proposed')} ({c.get('continuous_proposed')} continuous, "
        f"{c.get('stitched_proposed')} stitched) → valid {c.get('valid')} (auto-repaired {c.get('repaired')}, "
        f"rejected {c.get('rejected')}) → after de-duplication **{c.get('final')} promos**.",
        "",
        "Every timestamp below comes from the screenplay itself (the model only points at beat IDs). "
        "Rules enforced in code: 20–60 s total, hook starts ≤ 3 s in, ends on the cliffhanger beat, "
        "never cuts a line mid-sentence.",
        "",
    ]
    if meta.get("errors"):
        lines += ["## Errors during the run", ""] + [f"- {k}: {v}" for k, v in meta["errors"].items()] + [""]
    lines += ["## Posting order", "", "| # | Promo | Type | Length | Episodes | Score |", "|---|---|---|---|---|---|"]
    lines += [f"| {p.rank} | {p.title or p.id} | {p.kind} | {p.duration:.0f}s | "
              f"{', '.join(str(e) for e in p.episodes)} | {p.final_score} |" for p in promos]
    lines += ["", "## Promos", ""] + [promo_markdown(p) + "\n" for p in promos]
    if meta.get("rejections"):
        lines += ["## Rejected candidates (why the validator refused them)", ""]
        lines += [f"- {r}" for r in meta["rejections"]]
    return "\n".join(lines) + "\n"


def promos_payload(result: RunResult) -> dict:
    return {"bible": result.bible, "meta": result.meta, "promos": [promo_dict(p) for p in result.promos]}


def run_failed(meta: dict) -> bool:
    """A run that produced nothing and recorded errors should not replace a previous good run."""
    return not meta.get("candidates", {}).get("final") and bool(meta.get("errors"))


def write_outputs(result: RunResult, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "promos.json").write_text(json.dumps(promos_payload(result), indent=1, ensure_ascii=False))
    (out_dir / "bible.json").write_text(json.dumps(result.bible, indent=1, ensure_ascii=False))
    (out_dir / "run_meta.json").write_text(json.dumps(result.meta, indent=1, ensure_ascii=False))
    (out_dir / "promos.csv").write_text(promos_csv(result.promos))
    (out_dir / "report.md").write_text(report_markdown(result.promos, result.bible, result.meta))


def load_run(out_dir: Path) -> tuple[list[Promo], dict, dict]:
    """Read a run written by write_outputs: (ranked promos, bible, meta)."""
    data = json.loads((Path(out_dir) / "promos.json").read_text())
    promos = [Promo.model_validate(p) for p in data["promos"]]
    return promos, data.get("bible", {}), data.get("meta", {})
