"""Command line: `python -m hookline run --input <dir|zip> --out <dir>`."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .llm import LLM, LLMConfig, PROVIDERS
from .parse import load_show


def parse_episodes(spec: str | None) -> list[int] | None:
    if not spec:
        return None
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out


def load_env_file(path: str | None) -> None:
    for p in [path] if path else [".env"]:
        if p and Path(p).exists():
            for line in Path(p).read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def build_llm(args, cache_dir: Path) -> LLM:
    cfg = LLMConfig.from_env(provider=args.provider, model=args.model, base_url=args.base_url,
                             temperature=args.temperature)
    return LLM(cfg, cache_dir=cache_dir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hookline", description="Find ranked promos in microdrama screenplays.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--input", required=True, help="folder of episode .txt files, a .zip, or one .txt")
        p.add_argument("--out", required=True, help="output folder")
        p.add_argument("--provider", choices=sorted(PROVIDERS), default=None)
        p.add_argument("--model", default=None)
        p.add_argument("--base-url", default=None)
        p.add_argument("--temperature", type=float, default=None)
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--episodes", default=None, help="e.g. 1-3 or 1,5,9")
        p.add_argument("--env-file", default=None)

    common(sub.add_parser("run", help="run the full pipeline"))
    ev = sub.add_parser("eval", help="baseline + stability evaluation for an existing run")
    common(ev)
    ev.add_argument("--alt-model", default=None, help="second model for the stability check")
    ev.add_argument("--stability-episodes", default="1-50")
    args = ap.parse_args(argv)
    load_env_file(args.env_file)

    show = load_show(args.input)
    for w in show.warnings:
        print(f"[parse warning] {w}", file=sys.stderr)
    out = Path(args.out)
    llm = build_llm(args, out / "raw")
    print(f"Hookline · {len(show.episodes)} episodes · {llm.cfg.provider}/{llm.cfg.model}", file=sys.stderr)

    if args.cmd == "run":
        from .pipeline import run_pipeline
        from .report import write_outputs

        res = run_pipeline(show, llm, max_workers=args.workers, episodes=parse_episodes(args.episodes),
                           progress=lambda m, f: print(f"[{f:4.0%}] {m}", file=sys.stderr))
        write_outputs(res, show, out)
        c = res.meta["candidates"]
        print(f"{c['final']} promos → {out}/report.md  (proposed {c['proposed']}, rejected {c['rejected']}, "
              f"calls {res.meta['llm_usage']['calls']}, est. cost ${res.meta['est_cost_usd_paid_tier']})")
        return 0

    from .evaluate import evaluate

    report = evaluate(out, show, llm, alt_model=args.alt_model,
                      stability_episodes=parse_episodes(args.stability_episodes), workers=args.workers)
    print(report["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
