"""Regression tests for the final review's findings."""
import io
import zipfile

import pytest

from hookline.llm import LLM, LLMConfig, LLMError
from hookline.parse import load_show, parse_episode_text, zip_to_pairs
from hookline.pipeline import run_pipeline
from hookline.report import report_markdown, run_failed

from .test_llm import DailyQuotaClient, FakeClient
from .test_pipeline import FakeLLM, make_ep


def test_lowercase_and_hour_timestamps_parse():
    text = "EPISODE NUMBER: Episode 1\n**CAMERA:**\nstart: (00:01.0) | end: (00:02.0)\nShot.\n\n" \
           "**JULIANA:**\nStart: (0:01:05.0) | End: (0:01:07.5)\n\"Hi.\"\n"
    ep, _ = parse_episode_text(text, 1)
    assert [(b.start, b.end) for b in ep.beats] == [(1.0, 2.0), (65.0, 67.5)]


def test_timestamp_on_header_line_parses():
    ep, _ = parse_episode_text("**JULIANA (Sad):** Start: (00:03.0) | End: (00:04.0)\n\"No.\"\n", 1)
    assert ep.beats[0].speaker == "JULIANA" and ep.beats[0].start == 3.0 and ep.beats[0].text == "No."


def test_unparseable_episode_warns_with_first_unrecognised_line():
    _, warnings = parse_episode_text("JULIANA: hello there\nnothing else\n", 4)
    assert any("JULIANA: hello there" in w for w in warnings)


def test_filename_episode_number_prefers_episode_marker():
    show = load_show([("S01E05.txt", "**CAMERA:**\nStart: (00:00.0) | End: (00:01.0)\nx\n"),
                      ("S01E06.txt", "**CAMERA:**\nStart: (00:00.0) | End: (00:01.0)\nx\n")])
    assert [e.num for e in show.episodes] == [5, 6]


def test_pipeline_skips_empty_episodes_and_raises_when_none_left():
    show = load_show([("1.txt", make_ep(1)), ("2.txt", "EPISODE NUMBER: Episode 2\nno beats\n")])
    result = run_pipeline(show, FakeLLM(), max_workers=1)
    assert result.meta["show_episodes"] == [1]
    with pytest.raises(ValueError):
        run_pipeline(load_show([("2.txt", "EPISODE NUMBER: Episode 2\n")]), FakeLLM(), max_workers=1)


def _zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buffer.getvalue()


def test_bad_zip_raises_value_error():
    with pytest.raises(ValueError, match="zip"):
        zip_to_pairs(b"not a zip")


def test_zip_too_large_rejected():
    with pytest.raises(ValueError, match="too large"):
        zip_to_pairs(_zip({"a.txt": "x" * 2000}), max_bytes=1000)


def test_daily_quota_trips_circuit_breaker(tmp_path):
    fake = DailyQuotaClient([])
    llm = LLM(LLMConfig(provider="gemini", model="m", api_key="k"), cache_dir=tmp_path, client=fake)
    for _ in range(2):
        with pytest.raises(LLMError, match="daily quota"):
            llm.json("s", f"u{_}", tag="t")
    assert len(fake.calls) == 1


class OmittingLLM(FakeLLM):
    """Batched mining reply leaves out episode 2 the first time."""

    def __init__(self):
        super().__init__()
        self.mine_calls = []

    def json(self, system, user, tag):
        out = super().json(system, user, tag)
        if tag.startswith("02_mine_eps"):
            self.mine_calls.append(tag)
            if len(self.mine_calls) == 1:
                out["episodes"] = [e for e in out["episodes"] if e["episode"] != 2]
        return out


def test_episode_omitted_from_batch_is_re_asked():
    show = load_show([("1.txt", make_ep(1)), ("2.txt", make_ep(2))])
    llm = OmittingLLM()
    result = run_pipeline(show, llm, max_workers=1, episodes_per_call=2)
    assert len(llm.mine_calls) == 2
    assert "E02-C1" in {p.id for p in result.promos}


class MalformedLLM(FakeLLM):
    def json(self, system, user, tag):
        out = super().json(system, user, tag)
        if tag.startswith("02_mine_eps"):
            out["episodes"][0]["candidates"].append({"title": "no beats at all"})
        return out


def test_malformed_candidates_are_logged_as_rejections():
    show = load_show([("1.txt", make_ep(1))])
    result = run_pipeline(show, MalformedLLM(), max_workers=1)
    assert any("malformed" in r for r in result.meta["rejections"])


class ExplodingJudge(FakeLLM):
    def json(self, system, user, tag):
        if "judge" in tag:
            raise LLMError("fake/model: daily quota exhausted")
        return super().json(system, user, tag)


def test_judge_failure_reason_is_recorded():
    show = load_show([("1.txt", make_ep(1)), ("2.txt", make_ep(2))])
    result = run_pipeline(show, ExplodingJudge(), max_workers=1)
    assert any("daily quota" in e for e in result.meta["errors"].values())


def test_errors_appear_in_report_and_failed_runs_are_detected():
    meta = {"candidates": {}, "errors": {"ep1-5": "daily quota exhausted"}, "show_episodes": [1]}
    assert "daily quota exhausted" in report_markdown([], {}, meta)
    assert run_failed({"candidates": {"final": 0}, "errors": {"ep1-5": "x"}})
    assert not run_failed({"candidates": {"final": 3}, "errors": {}})
