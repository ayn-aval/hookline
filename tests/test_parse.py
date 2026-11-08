from pathlib import Path

import pytest

from hookline.parse import fmt_ts, load_show, parse_episode_text

EP1 = """EPISODE NUMBER: Episode 1
EPISODE LOGLINE: Juliana is jilted at the altar.
CONTINUITY NOTES: First episode.

--- SCRIPT START ---

SCENE 01
Scene heading: INT. CATHEDRAL – DAY
Scene start: 00:00.00
Scene end: 00:20.00

Actions and dialogue:

**CAMERA:**
Start: (00:00.00) | End: (00:04.80)
Doors part as Juliana stands framed in light.

**MATRIARCH (Cold, Commanding):**
Start: (00:11.30) | End: (00:13.10)
"You should turn around, Juliana."

**ACTION:**
Start: (00:13.20) | End: (00:15.00)
Juliana freezes.

**SOUND FX:**
Start: (00:15.00) | End: (00:17.50)
Ominous string drone.

--- SCRIPT END ---
"""


def test_parse_episode1():
    ep, warnings = parse_episode_text(EP1, fallback_num=99)
    assert ep.num == 1
    assert ep.logline == "Juliana is jilted at the altar."
    assert [b.kind for b in ep.beats] == ["CAMERA", "DIALOGUE", "ACTION", "SFX"]
    d = ep.beats[1]
    assert d.speaker == "MATRIARCH"
    assert d.emotion == "Cold, Commanding"
    assert d.start == 11.3 and d.end == 13.1
    assert d.text == "You should turn around, Juliana."
    assert d.id == "E01-B002"
    assert d.scene == 1
    assert ep.duration == 17.5
    assert warnings == []


def test_parse_tolerates_variants():
    text = """EPISODE NUMBER: Episode 3

SCENE 1
**CAMERA:**
Start: (1:02.5) | End: (1:04.0)
Wide shot.

**GERALD:**
Start: (1:04.0) | End: (1:05.5)
  "Never."

**BROKEN BEAT:**
no timestamps here
"""
    ep, warnings = parse_episode_text(text, fallback_num=7)
    assert ep.num == 3
    assert ep.beats[0].start == 62.5
    assert ep.beats[1].speaker == "GERALD" and ep.beats[1].emotion is None
    assert ep.beats[1].text == "Never."
    assert len(ep.beats) == 2
    assert any("logline" in w.lower() for w in warnings)
    assert any("BROKEN BEAT" in w for w in warnings)


def test_parse_falls_back_to_filename_number():
    ep, _ = parse_episode_text("**CAMERA:**\nStart: (00:00.00) | End: (00:01.00)\nx\n", fallback_num=12)
    assert ep.num == 12
    assert ep.beats[0].id == "E12-B001"


def test_fmt_ts():
    assert fmt_ts(65.3) == "01:05.30"
    assert fmt_ts(0) == "00:00.00"


def test_load_show_from_pairs_sorts_by_episode():
    show = load_show([("b.txt", EP1.replace("Episode 1", "Episode 2")), ("a.txt", EP1)])
    assert [e.num for e in show.episodes] == [1, 2]


DATA = Path(__file__).resolve().parents[1] / "data"


@pytest.mark.skipif(not DATA.exists(), reason="confidential input pack not present")
def test_load_show_real_pack():
    show = load_show(DATA)
    assert len(show.episodes) == 50
    assert sum(len(e.beats) for e in show.episodes) >= 3700
    assert show.episodes[0].num == 1 and show.episodes[-1].num == 50
