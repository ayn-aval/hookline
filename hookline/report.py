"""Write run outputs: promos.json, promos.csv, report.md, run_meta.json, bible.json.

Committed outputs carry timestamps + short hook/cliffhanger quotes only, never the screenplay itself.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .parse import fmt_ts
from .schemas import ParseResult, Promo

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


def write_csv(promos: list[Promo], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for p in promos:
            for n, s in enumerate(p.segments, 1):
                w.writerow([p.rank, p.id, p.kind, p.title, p.duration, n, s.ep, fmt_ts(s.start), fmt_ts(s.end),
                            round(s.end - s.start, 2), p.hook, p.cliffhanger, p.why, p.post_reason, p.final_score,
                            p.scores.get("hook"), p.scores.get("cliff"), p.scores.get("standalone"),
                            p.scores.get("emotion"), p.spoiler, p.repaired])


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


def write_report(promos: list[Promo], bible: dict, meta: dict, path: Path, title: str = "Hookline promo report") -> None:
    c = meta.get("candidates", {})
    eps = meta.get("show_episodes") or []
    head = [
        f"# {title}",
        "",
        f"**Show premise (from series bible):** {bible.get('show_premise', '')}",
        "",
        f"Episodes {min(eps) if eps else '?'}–{max(eps) if eps else '?'} · model `{meta.get('provider')}/{meta.get('model')}`"
        f" · prompts `{meta.get('prompts_sha')}` · {meta.get('seconds')}s · "
        f"LLM calls {meta.get('llm_usage', {}).get('calls')} (cached {meta.get('llm_usage', {}).get('cached')})",
        "",
        f"Candidates proposed {c.get('proposed')} ({c.get('continuous_proposed')} continuous, "
        f"{c.get('stitched_proposed')} stitched) → valid {c.get('valid')} (auto-repaired {c.get('repaired')}, "
        f"rejected {c.get('rejected')}) → after de-duplication **{c.get('final')} promos**.",
        "",
        "Every timestamp below comes from the screenplay itself (the model only points at beat IDs). "
        "Rules enforced in code: 20–60 s total, hook starts ≤ 3 s in, ends on the cliffhanger beat, never cuts a line mid-sentence.",
        "",
        "## Posting order",
        "",
        "| # | Promo | Type | Length | Episodes | Score |",
        "|---|---|---|---|---|---|",
    ]
    for p in promos:
        head.append(f"| {p.rank} | {p.title or p.id} | {p.kind} | {p.duration:.0f}s | "
                    f"{', '.join(str(e) for e in p.episodes)} | {p.final_score} |")
    body = ["", "## Promos", ""] + [promo_markdown(p) + "\n" for p in promos]
    if meta.get("rejections"):
        body += ["## Rejected candidates (why the validator refused them)", ""]
        body += [f"- {r}" for r in meta["rejections"]]
    path.write_text("\n".join(head + body) + "\n")


def write_outputs(result, show: ParseResult, out_dir: Path) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "promos.json").write_text(json.dumps(
        {"bible": result.bible, "meta": result.meta, "promos": [promo_dict(p) for p in result.promos]},
        indent=1, ensure_ascii=False))
    (out_dir / "bible.json").write_text(json.dumps(result.bible, indent=1, ensure_ascii=False))
    (out_dir / "run_meta.json").write_text(json.dumps(result.meta, indent=1, ensure_ascii=False))
    write_csv(result.promos, out_dir / "promos.csv")
    write_report(result.promos, result.bible, result.meta, out_dir / "report.md")
