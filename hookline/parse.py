"""Deterministic screenplay parser: text files -> timestamped beats with stable IDs.

Tolerant by design: a new show may differ slightly in format, so anything that cannot be
parsed becomes a warning, never a crash.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Iterable, Optional, Union

from .schemas import Beat, Episode, ParseResult

_TS = r"\(?\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*\)?"
TIME_RE = re.compile(rf"Start:\s*{_TS}\s*\|\s*End:\s*{_TS}", re.I)
HEADER_RE = re.compile(r"^\*\*(.+?):?\*\*:?\s*(.*)$")
SPEAKER_RE = re.compile(r"^(.*?)\s*\((.*)\)\s*$")
EP_NUM_RE = re.compile(r"EPISODE NUMBER:\s*(?:Episode\s*)?(\d+)", re.I)
SCENE_RE = re.compile(r"^SCENE\s+(\d+)", re.I)
FIELD_RE = {
    "logline": re.compile(r"^EPISODE LOGLINE:\s*(.*)$", re.I | re.M),
    "continuity": re.compile(r"^CONTINUITY NOTES:\s*(.*)$", re.I | re.M),
}
FILENAME_EP_RE = re.compile(r"(?:episode|ep|e)[\s_-]*(\d+)", re.I)
FIRST_NUMBER_RE = re.compile(r"(\d+)")
KIND_MAP = {"CAMERA": "CAMERA", "ACTION": "ACTION", "SOUND FX": "SFX", "SFX": "SFX", "SOUND": "SFX"}
STRUCTURE_PREFIXES = ("--- SCRIPT", "SCENE ", "Scene heading:", "Scene start:", "Scene end:",
                      "Actions and dialogue:", "EPISODE ", "CONTINUITY NOTES:")
OPENING_QUOTES, CLOSING_QUOTES = "\"“", "\"”"

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_ZIP_FILES = 500


def fmt_ts(sec: float) -> str:
    """Seconds -> 'MM:SS.ss', the screenplay's own format."""
    sec = max(0.0, float(sec))
    minutes = int(sec // 60)
    return f"{minutes:02d}:{sec - 60 * minutes:05.2f}"


def _seconds(hours: Optional[str], minutes: str, seconds: str) -> float:
    return round(int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds), 2)


def _times(match: re.Match) -> tuple[float, float]:
    g = match.groups()
    return _seconds(*g[:3]), _seconds(*g[3:])


def _beat_kind(label: str) -> tuple[str, Optional[str], Optional[str]]:
    """(kind, speaker, emotion) for a header label such as 'CAMERA' or 'JULIANA (Angry)'."""
    kind = KIND_MAP.get(label.upper())
    if kind:
        return kind, None, None
    match = SPEAKER_RE.match(label)
    if match:
        return "DIALOGUE", match.group(1).strip(), match.group(2).strip()
    return "DIALOGUE", label, None


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] in OPENING_QUOTES and text[-1] in CLOSING_QUOTES:
        return text[1:-1].strip()
    return text


def parse_episode_text(text: str, fallback_num: int) -> tuple[Episode, list[str]]:
    warnings: list[str] = []
    match = EP_NUM_RE.search(text)
    num = int(match.group(1)) if match else fallback_num
    if not match:
        warnings.append(f"ep{fallback_num}: no EPISODE NUMBER line; using {fallback_num} from the file name/order")
    meta = {key: (m.group(1).strip() if (m := rx.search(text)) else "") for key, rx in FIELD_RE.items()}
    if not meta["logline"]:
        warnings.append(f"ep{num}: missing EPISODE LOGLINE")

    lines = text.splitlines()
    beats: list[Beat] = []
    first_unrecognised: Optional[str] = None
    scene = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        scene_match = SCENE_RE.match(line)
        if scene_match:
            scene = int(scene_match.group(1))
            i += 1
            continue
        header = HEADER_RE.match(line)
        if not header:
            if line and first_unrecognised is None and not line.startswith(STRUCTURE_PREFIXES):
                first_unrecognised = line
            i += 1
            continue
        label, rest = header.group(1).strip(), header.group(2)
        time_match = TIME_RE.search(rest)
        body_from = i + 1
        if not time_match:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            time_match = TIME_RE.search(lines[j]) if j < len(lines) else None
            body_from = j + 1
        if not time_match:
            warnings.append(f"ep{num}: beat '{label}' near line {i + 1} has no timestamps; skipped")
            i += 1
            continue
        start, end = _times(time_match)
        k = body_from
        body: list[str] = []
        while k < len(lines):
            stripped = lines[k].strip()
            if HEADER_RE.match(stripped) or stripped.startswith(STRUCTURE_PREFIXES):
                break
            if stripped:
                body.append(stripped)
            k += 1
        kind, speaker, emotion = _beat_kind(label)
        content = " ".join(body).strip()
        if kind == "DIALOGUE":
            content = _strip_quotes(content)
        if end < start:
            warnings.append(f"ep{num}: beat '{label}' at {fmt_ts(start)} ends before it starts; swapped")
            start, end = end, start
        beats.append(Beat(id=f"E{num:02d}-B{len(beats) + 1:03d}", ep=num, scene=scene or 1, kind=kind,
                          speaker=speaker, emotion=emotion, start=start, end=end, text=content))
        i = k
    if not beats:
        hint = f"; first unrecognised line: {first_unrecognised[:80]!r}" if first_unrecognised else ""
        warnings.append(f"ep{num}: no beats parsed{hint}")
    episode = Episode(num=num, title=f"Episode {num}", logline=meta["logline"], continuity=meta["continuity"],
                      beats=beats, duration=max((b.end for b in beats), default=0.0))
    return episode, warnings


def _fallback_num(name: str, position: int) -> int:
    stem = Path(name).stem
    match = FILENAME_EP_RE.search(stem) or FIRST_NUMBER_RE.search(stem)
    return int(match.group(1)) if match else position + 1


def zip_to_pairs(data: bytes, max_bytes: int = MAX_ZIP_BYTES,
                 max_files: int = MAX_ZIP_FILES) -> list[tuple[str, str]]:
    """Read the .txt members of a zip, refusing corrupt or oversized archives."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("not a valid zip file") from exc
    with archive:
        members = [m for m in archive.infolist()
                   if m.filename.lower().endswith(".txt") and "__MACOSX" not in m.filename
                   and not Path(m.filename).name.startswith("._")]
        if len(members) > max_files:
            raise ValueError(f"zip has too many files ({len(members)} > {max_files})")
        if sum(m.file_size for m in members) > max_bytes:
            raise ValueError(f"zip is too large when extracted (limit {max_bytes // (1024 * 1024)} MB)")
        return [(m.filename, archive.read(m).decode("utf-8", "replace"))
                for m in sorted(members, key=lambda m: m.filename)]


def _read_inputs(src) -> list[tuple[str, str]]:
    if isinstance(src, (list, tuple)):
        return [(str(n), t if isinstance(t, str) else t.decode("utf-8", "replace")) for n, t in src]
    path = Path(src)
    if path.is_dir():
        return [(f.name, f.read_text("utf-8", "replace")) for f in sorted(path.glob("*.txt"))]
    if path.suffix.lower() == ".zip":
        return zip_to_pairs(path.read_bytes())
    return [(path.name, path.read_text("utf-8", "replace"))]


def load_show(src: Union[str, Path, Iterable[tuple[str, str]]]) -> ParseResult:
    """Load a show from a directory of .txt files, a .zip, a single file, or (name, text) pairs."""
    episodes, warnings, seen = [], [], set()
    for position, (name, text) in enumerate(_read_inputs(src)):
        episode, episode_warnings = parse_episode_text(text, _fallback_num(name, position))
        if episode.num in seen:
            warnings.append(f"duplicate episode number {episode.num} in {name}; skipped")
            continue
        seen.add(episode.num)
        episodes.append(episode)
        warnings.extend(episode_warnings)
    episodes.sort(key=lambda e: e.num)
    return ParseResult(episodes=episodes, warnings=warnings)
