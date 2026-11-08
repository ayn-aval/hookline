"""Data shapes shared by every stage of the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, Field

BeatKind = Literal["CAMERA", "ACTION", "DIALOGUE", "SFX", "OTHER"]


class Beat(BaseModel):
    """One timestamped line of the screenplay (a camera note, an action, a spoken line, a sound)."""

    id: str  # e.g. "E07-B031" — the ONLY way the LLM may refer to a moment
    ep: int
    scene: int
    kind: BeatKind
    speaker: Optional[str] = None
    emotion: Optional[str] = None
    start: float  # seconds from episode start
    end: float
    text: str


class Episode(BaseModel):
    num: int
    title: str = ""
    logline: str = ""
    continuity: str = ""
    beats: list[Beat] = Field(default_factory=list)
    duration: float = 0.0


class ParseResult(BaseModel):
    episodes: list[Episode]
    warnings: list[str] = Field(default_factory=list)

    def beat_index(self) -> dict[str, Beat]:
        return {b.id: b for e in self.episodes for b in e.beats}

    def episode(self, num: int) -> Episode:
        for e in self.episodes:
            if e.num == num:
                return e
        raise KeyError(num)


# ---- candidates (what the LLM proposes, by beat id) and promos (validated, timestamped) ----


class SegmentRef(BaseModel):
    start_beat: str
    end_beat: str


class Candidate(BaseModel):
    id: str
    kind: Literal["continuous", "stitched"]
    title: str = ""
    segments: list[SegmentRef]
    hook_beat: str
    cliff_beat: str
    hook: str = ""
    cliffhanger: str = ""
    why: str = ""


class Segment(BaseModel):
    ep: int
    start: float
    end: float
    start_beat: str
    end_beat: str

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)


class Promo(BaseModel):
    id: str
    kind: Literal["continuous", "stitched", "baseline"]
    title: str = ""
    segments: list[Segment]
    duration: float
    hook: str = ""
    cliffhanger: str = ""
    why: str = ""
    hook_beat: str
    cliff_beat: str
    repaired: bool = False
    repairs: list[str] = Field(default_factory=list)
    scores: dict = Field(default_factory=dict)
    spoiler: int = 0
    final_score: float = 0.0
    rank: Optional[int] = None
    post_reason: str = ""

    @property
    def episodes(self) -> list[int]:
        return sorted({s.ep for s in self.segments})

    @property
    def judged(self) -> bool:
        return self.scores.get("judged", True) is not False


@dataclass
class RunResult:
    promos: list[Promo]
    bible: dict
    meta: dict = field(default_factory=dict)
