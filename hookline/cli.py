"""Command line interface.

    python -m hookline run     --input <dir|zip> --out <dir>
    python -m hookline eval    --input <dir|zip> --out <dir> [--alt-model NAME]
    python -m hookline inspect --input <dir|zip> --out <dir> [--top N | --ids ID ...]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from .llm import LLM, PROVIDERS, LLMConfig
from .parse import load_show


def parse_episodes(spec: Optional[str]) -> Optional[list[int]]:
    """'1-3,7' -> [1, 2, 3, 7]."""
    if not spec:
        return None
    episodes: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            first, last = part.split("-")
            episodes += list(range(int(first), int(last) + 1))
        elif part:
            episodes.append(int(part))
    return episodes


def load_env_file(path: Optional[str]) -> None:
    candidate = Path(path) if path else Path(".env")
    if not candidate.exists():
        return
    for line in candidate.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--input", required=True, help="folder of episode .txt files, a .zip, or one .txt")
    p.add_argument("--out", required=True, help="output folder of the run")
    p.add_argument("--provider", choices=sorted(PROVIDERS), default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None, help="any OpenAI-compatible endpoint")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--workers", type=int, default=4, help="parallel LLM calls")
    p.add_argument("--episodes", default=None, help="subset, e.g. 1-3 or 1,5,9")
    p.add_argument("--env-file", default=None, help="file with GEMINI_API_KEY / HOOKLINE_* variables")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hookline", description="Find ranked promos in microdrama screenplays.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    _add_common(sub.add_parser("run", help="run the full pipeline"))
    ev = sub.add_parser("eval", help="baseline, stability and constraint checks for an existing run")
    _add_common(ev)
    ev.add_argument("--alt-model", default=None, help="second model for the stability check")
    ev.add_argument("--eval-dir", default=None)
    ins = sub.add_parser("inspect", help="print the screenplay lines of ranked promos")
    _add_common(ins)
    ins.add_argument("--top", type=int, default=5)
    ins.add_argument("--ids", nargs="*", default=None)
    return parser


def _llm(args, cache_dir: Path, **overrides) -> LLM:
    cfg = LLMConfig.from_env(provider=args.provider, model=args.model, base_url=args.base_url,
                             temperature=args.temperature)
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return LLM(cfg, cache_dir=cache_dir)


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def cmd_run(args, show) -> int:
    from .pipeline import run_pipeline
    from .report import write_outputs

    out = Path(args.out)
    llm = _llm(args, out / "raw")
    _log(f"Hookline · {len(show.episodes)} episodes · {llm.cfg.provider}/{llm.cfg.model}")
    result = run_pipeline(show, llm, max_workers=args.workers, episodes=parse_episodes(args.episodes),
                          progress=lambda m, f: _log(f"[{f:4.0%}] {m}"))
    write_outputs(result, show, out)
    c = result.meta["candidates"]
    print(f"{c['final']} promos -> {out / 'report.md'} (proposed {c['proposed']}, rejected {c['rejected']}, "
          f"LLM calls {result.meta['llm_usage']['calls']}, est. paid-tier cost ${result.meta['est_cost_usd_paid_tier']})")
    return 0


def cmd_eval(args, show) -> int:
    from .evaluate import evaluate

    out = Path(args.out)
    llm = _llm(args, out / "raw")
    alt = (_llm(args, out / "raw_alt", model=args.alt_model) if args.alt_model
           else _llm(args, out / "raw_alt", temperature=0.9))
    report = evaluate(out, show, llm, alt_llm=alt, eval_dir=Path(args.eval_dir) if args.eval_dir else None,
                      workers=args.workers, stability_episodes=parse_episodes(args.episodes))
    print(report["markdown"])
    return 0


def cmd_inspect(args, show) -> int:
    from .render import clip_block
    from .report import load_run

    promos, _, _ = load_run(Path(args.out))
    chosen = [p for p in promos if p.id in set(args.ids)] if args.ids else promos[:args.top]
    for p in chosen:
        print(f"#{p.rank} {p.title} [{p.kind}, {p.duration:.1f}s]")
        print(clip_block(p, show), end="\n\n")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(args.env_file)
    show = load_show(args.input)
    for warning in show.warnings:
        _log(f"[parse warning] {warning}")
    return {"run": cmd_run, "eval": cmd_eval, "inspect": cmd_inspect}[args.cmd](args, show)


if __name__ == "__main__":
    raise SystemExit(main())
