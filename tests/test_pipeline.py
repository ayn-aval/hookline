import json

from hookline.parse import load_show
from hookline.pipeline import run_pipeline
from hookline.report import write_outputs
from hookline.baseline import baseline_promos


def make_ep(n: int) -> str:
    lines = [f"EPISODE NUMBER: Episode {n}", f"EPISODE LOGLINE: Logline {n}.", "CONTINUITY NOTES: none.", "",
             "SCENE 01"]
    for i in range(12):  # 12 beats x 5 s = 60 s episode
        m, s = divmod(i * 5, 60)
        m2, s2 = divmod(i * 5 + 5, 60)
        lines += [f"**JULIANA (Angry):**", f"Start: ({m:02d}:{s:05.2f}) | End: ({m2:02d}:{s2:05.2f})",
                  f'"Line {i + 1} of episode {n}."', ""]
    return "\n".join(lines)


MINED = {
    1: {"candidates": [
        {"title": "good", "start_beat": "E01-B002", "end_beat": "E01-B008", "hook_beat": "E01-B002",
         "cliff_beat": "E01-B008", "hook": "h", "cliffhanger": "c", "why": "w"},
        {"title": "invented", "start_beat": "E01-B002", "end_beat": "E01-B099", "hook_beat": "E01-B002",
         "cliff_beat": "E01-B099", "hook": "h", "cliffhanger": "c", "why": "w"}],
        "moments": [{"beat": "E01-B003", "type": "hook", "note": "n"}]},
    2: {"candidates": [
        {"title": "spoiler", "start_beat": "E02-B005", "end_beat": "E02-B011", "hook_beat": "E02-B005",
         "cliff_beat": "E02-B011", "hook": "h", "cliffhanger": "c", "why": "w"}],
        "moments": [{"beat": "E02-B009", "type": "cliff", "note": "n"}]},
}


class FakeLLM:
    """Replies by tag prefix; records the user prompts it saw."""

    def __init__(self):
        self.seen = {}
        self.usage = {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0, "retries": 0}
        self.cfg = type("C", (), {"provider": "fake", "model": "fake-1", "temperature": 0})()

    def json(self, system, user, tag):
        self.seen[tag] = user
        self.usage["calls"] += 1
        if tag.startswith("01_bible"):
            return {"show_premise": "A jilted bride.", "characters": [], "arcs": [],
                    "reveals": [{"reveal": "x", "episode": 2, "ad_safe": False, "keywords": ["line 11 of episode 2"]}]}
        if tag.startswith("02_mine_eps"):
            nums = [int(line.split()[1]) for line in user.splitlines() if line.startswith("EPISODE ")]
            return {"episodes": [{"episode": n, **MINED.get(n, {"candidates": [], "moments": []})} for n in nums]}
        if tag.startswith("03_stitch"):
            return {"promos": [{"title": "st", "segments": [{"start_beat": "E02-B001", "end_beat": "E02-B002"},
                                                            {"start_beat": "E01-B009", "end_beat": "E01-B011"}],
                                "hook_beat": "E02-B001", "cliff_beat": "E01-B011", "hook": "h", "cliffhanger": "c",
                                "why": "w"}]}
        if "judge" in tag:
            ids = [l.split("CLIP ")[1].split(" ")[0] for l in user.splitlines() if l.startswith("=== CLIP ")]
            return {"scores": [{"id": i, "hook": 4, "cliff": 4, "standalone": 4, "emotion": 4,
                                "cold_viewer_summary": "s", "weakness": "w"} for i in ids]}
        raise AssertionError(tag)


def test_pipeline_end_to_end_fake_llm(tmp_path):
    show = load_show([("1.txt", make_ep(1)), ("2.txt", make_ep(2))])
    llm = FakeLLM()
    result = run_pipeline(show, llm, max_workers=2)
    ids = {p.id for p in result.promos}
    assert ids == {"E01-C1", "E02-C1", "S01"}
    beats = show.beat_index()
    starts = {b.start for b in beats.values()}
    for p in result.promos:
        assert 20 <= p.duration <= 60
        assert p.rank is not None and p.scores["hook"] == 4
        for s in p.segments:
            assert s.start in starts
    spoiler = next(p for p in result.promos if p.id == "E02-C1")
    assert spoiler.spoiler == 2
    assert result.meta["candidates"]["rejected"] == 1
    assert any("unknown" in r for r in result.meta["rejections"])
    # judge saw only the clip text: no bible/premise leaked into its prompt
    judge_prompt = next(v for k, v in llm.seen.items() if k.startswith("04_judge"))
    assert "jilted bride" not in judge_prompt
    write_outputs(result, show, tmp_path)
    for f in ["promos.json", "promos.csv", "report.md", "run_meta.json"]:
        assert (tmp_path / f).exists()
    data = json.loads((tmp_path / "promos.json").read_text())
    assert data["promos"][0]["rank"] == 1
    assert "Line 3 of episode 1" not in (tmp_path / "report.md").read_text()  # no script text beyond quotes


def test_baseline_promos_last_45s():
    show = load_show([("1.txt", make_ep(1))])
    [p] = baseline_promos(show)
    assert p.kind == "baseline"
    assert p.segments[0].end == 60.0
    assert 40 <= p.duration <= 50


class ForgetfulJudgeLLM(FakeLLM):
    """First judge call omits one clip id, like the real model did in the smoke run."""

    def __init__(self):
        super().__init__()
        self.judge_calls = 0

    def json(self, system, user, tag):
        out = super().json(system, user, tag)
        if "judge" in tag:
            self.judge_calls += 1
            if self.judge_calls == 1 and len(out["scores"]) > 1:
                out["scores"] = out["scores"][1:]
        return out


def test_judge_rescores_clips_the_model_skipped(tmp_path):
    show = load_show([("1.txt", make_ep(1)), ("2.txt", make_ep(2))])
    llm = ForgetfulJudgeLLM()
    result = run_pipeline(show, llm, max_workers=1)
    assert all(p.scores.get("hook") == 4 for p in result.promos)
    assert llm.judge_calls == 2


class BrokenJudgeLLM(FakeLLM):
    def json(self, system, user, tag):
        if "judge" in tag:
            return {"scores": []}
        return super().json(system, user, tag)


def test_unjudged_promo_is_flagged_not_scored_zero(tmp_path):
    show = load_show([("1.txt", make_ep(1)), ("2.txt", make_ep(2))])
    result = run_pipeline(show, BrokenJudgeLLM(), max_workers=1)
    assert all(p.scores.get("judged") is False for p in result.promos)
    assert all("not scored" in p.post_reason for p in result.promos)


def test_episodes_per_call_batches_mining_and_judge_uses_its_own_model(tmp_path):
    show = load_show([("1.txt", make_ep(1)), ("2.txt", make_ep(2))])
    gen, judge = FakeLLM(), FakeLLM()
    result = run_pipeline(show, gen, judge_llm=judge, max_workers=1, episodes_per_call=2)
    assert {p.id for p in result.promos} == {"E01-C1", "E02-C1", "S01"}
    assert [t for t in gen.seen if t.startswith("02_mine_eps")] == ["02_mine_eps01-02"]
    assert not any("judge" in t for t in gen.seen)
    assert any("judge" in t for t in judge.seen)
    assert result.meta["judge_model"] == "fake-1"
