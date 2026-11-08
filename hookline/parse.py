"""Deterministic screenplay parser: text files -> timestamped beats with stable IDs.

Tolerant by design: a new show may differ slightly in format, so anything we can't
parse becomes a warning, never a crash.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Iterable, Union

from .schemas import Beat, Episode, ParseResult

HEADER_RE = re.compile(r"^\*\*(.+?):?\*\*:?\s*$")
TIME_RE = re.compile(
    r"Start:\s*\(?\s*(\d+):(\d+(?:\.\d+)?)\s*\)?\s*\|\s*End:\s*\(?\s*(\d+):(\d+(?:\.\d+)?)\s*\)?"
)
SPEAKER_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")
EP_NUM_RE = re.compile(r"EPISODE NUMBER:\s*(?:Episode\s*)?(\d+)", re.I)
SCENE_RE = re.compile(r"^SCENE\s+(\d+)", re.I)
FIELD_RE = {
    "logline": re.compile(r"^EPISODE LOGLINE:\s*(.*)$", re.I | re.M),
    "continuity": re.compile(r"^CONTINUITY NOTES:\s*(.*)$", re.I | re.M),
}
KIND_MAP = {"CAMERA": "CAMERA", "ACTION": "ACTION", "SOUND FX": "SFX", "SFX": "SFX", "SOUND": "SFX"}
STOP_LINES = ("--- SCRIPT", "SCENE ", "Scene heading:", "Scene start:", "Scene end:", "Actions and dialogue:")


def fmt_ts(sec: float) -> str:
    """Seconds -> 'MM:SS.ss' (the screenplay's own format)."""
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    return f"{m:02d}:{sec - 60 * m:05.2f}"


def _secs(m: str, s: str) -> float:
    return round(int(m) * 60 + float(s), 2)


def parse_episode_text(text: str, fallback_num: int) -> tuple[Episode, list[str]]:
    warnings: list[str] = []
    m = EP_NUM_RE.search(text)
    num = int(m.group(1)) if m else fallback_num
    if not m:
        warnings.append(f"ep{fallback_num}: no EPISODE NUMBER line; using {fallback_num} from file order/name")
    meta = {}
    for key, rx in FIELD_RE.items():
        mm = rx.search(text)
        meta[key] = mm.group(1).strip() if mm else ""
    if not meta["logline"]:
        warnings.append(f"ep{num}: missing EPISODE LOGLINE")

    lines = text.splitlines()
    beats: list[Beat] = []
    scene = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        sm = SCENE_RE.match(line)
        if sm:
            scene = int(sm.group(1))
            i += 1
            continue
        hm = HEADER_RE.match(line)
        if not hm:
            i += 1
            continue
        label = hm.group(1).strip()
        # find timestamp line (next non-empty line)
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        tm = TIME_RE.search(lines[j]) if j < len(lines) else None
        if not tm:
            warnings.append(f"ep{num}: beat '{label}' near line {i + 1} has no timestamps; skipped")
            i += 1
            continue
        start, end = _secs(tm.group(1), tm.group(2)), _secs(tm.group(3), tm.group(4))
        # text = following non-empty lines until next header / structural line
        k = j + 1
        body: list[str] = []
        while k < len(lines):
            s = lines[k].strip()
            if HEADER_RE.match(s) or s.startswith(STOP_LINES):
                break
            if s:
                body.append(s)
            k += 1
        txt = " ".join(body).strip()
        upper = label.upper()
        kind = KIND_MAP.get(upper)
        speaker = emotion = None
        if kind is None:
            kind = "DIALOGUE"
            sp = SPEAKER_RE.match(label)
            speaker, emotion = (sp.group(1).strip(), sp.group(2).strip()) if sp else (label, None)
            if len(txt) >= 2 and txt[0] in "\"“" and txt[-1] in "\"”":
                txt = txt[1:-1].strip()
        if end < start:
            warnings.append(f"ep{num}: beat '{label}' at {fmt_ts(start)} ends before it starts; swapped")
            start, end = end, start
        beats.append(
            Beat(
                id=f"E{num:02d}-B{len(beats) + 1:03d}",
                ep=num,
                scene=scene or 1,
                kind=kind,
                speaker=speaker,
                emotion=emotion,
                start=start,
                end=end,
                text=txt,
            )
        )
        i = k
    if not beats:
        warnings.append(f"ep{num}: no beats parsed")
    duration = max((b.end for b in beats), default=0.0)
    return (
        Episode(num=num, title=f"Episode {num}", logline=meta["logline"], continuity=meta["continuity"],
                beats=beats, duration=duration),
        warnings,
    )


_NUM_IN_NAME = re.compile(r"(\d+)")


def _fallback_num(name: str, pos: int) -> int:
    m = _NUM_IN_NAME.search(Path(name).name)
    return int(m.group(1)) if m else pos + 1


def _read_inputs(src) -> list[tuple[str, str]]:
    if isinstance(src, (list, tuple)):
        return [(str(n), t if isinstance(t, str) else t.decode("utf-8", "replace")) for n, t in src]
    p = Path(src)
    if p.is_dir():
        return [(f.name, f.read_text("utf-8", "replace")) for f in sorted(p.glob("*.txt"))]
    if p.suffix.lower() == ".zip":
        return zip_to_pairs(p.read_bytes())
    return [(p.name, p.read_text("utf-8", "replace"))]


def zip_to_pairs(data: bytes) -> list[tuple[str, str]]:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in sorted(z.namelist()):
            if n.lower().endswith(".txt") and not Path(n).name.startswith("._") and "__MACOSX" not in n:
                out.append((n, z.read(n).decode("utf-8", "replace")))
    return out


def load_show(src: Union[str, Path, Iterable[tuple[str, str]]]) -> ParseResult:
    """Load a show from a directory of .txt files, a .zip, a single file, or (name, text) pairs."""
    pairs = _read_inputs(src)
    episodes, warnings = [], []
    seen = set()
    for pos, (name, text) in enumerate(pairs):
        ep, w = parse_episode_text(text, _fallback_num(name, pos))
        if ep.num in seen:
            warnings.append(f"duplicate episode number {ep.num} in {name}; skipped")
            continue
        seen.add(ep.num)
        episodes.append(ep)
        warnings.extend(w)
    episodes.sort(key=lambda e: e.num)
    return ParseResult(episodes=episodes, warnings=warnings)
