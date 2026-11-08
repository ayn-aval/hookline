import json

from hookline.evaluate import evaluate, top_overlap
from hookline.parse import load_show
from hookline.pipeline import run_pipeline
from hookline.report import write_outputs
from hookline.schemas import Promo, Segment

from .test_pipeline import FakeLLM, make_ep


def P(pid, ep, start, end):
    return Promo(id=pid, kind="continuous", segments=[Segment(ep=ep, start=start, end=end, start_beat="x",
                                                              end_beat="y")],
                 duration=end - start, hook_beat="x", cliff_beat="y")


def test_top_overlap_counts_refound_promos():
    main = [P("a", 1, 0, 40), P("b", 2, 0, 40)]
    alt = [P("x", 1, 5, 42), P("y", 3, 0, 40)]
    assert top_overlap(main, alt) == 0.5


def test_evaluate_writes_results(tmp_path):
    show = load_show([("1.txt", make_ep(1)), ("2.txt", make_ep(2))])
    llm = FakeLLM()
    write_outputs(run_pipeline(show, llm, max_workers=1), tmp_path)
    report = evaluate(tmp_path, show, llm, alt_llm=FakeLLM(), eval_dir=tmp_path / "eval", workers=1)
    data = json.loads((tmp_path / "eval" / "results.json").read_text())
    assert data["baseline"]["n"] == 2
    assert set(data["baseline"]["mean"]) >= {"hook", "cliff", "standalone", "emotion", "weighted"}
    assert data["stability"]["top10_refound"] == 1.0
    assert data["constraints"]["final"] == 3
    assert "Baseline" in report["summary"]
    assert (tmp_path / "eval" / "results.md").exists()


def test_stability_only_counts_promos_inside_the_remined_episodes():
    from hookline.evaluate import stability_targets

    ranked = [P("late", 40, 0, 40), P("early", 1, 0, 40), P("mid", 20, 0, 40)]
    assert [p.id for p in stability_targets(ranked, episodes=[1, 2, 3])] == ["early"]
    assert [p.id for p in stability_targets(ranked, episodes=None)] == ["late", "early", "mid"]


def test_results_include_like_for_like_baseline_best():
    from hookline.evaluate import best_by_judge

    a, b = P("a", 1, 0, 40), P("b", 2, 0, 40)
    a.scores = {"hook": 1, "cliff": 1, "standalone": 1, "emotion": 1}
    b.scores = {"hook": 5, "cliff": 5, "standalone": 5, "emotion": 5}
    assert [p.id for p in best_by_judge([a, b], 1)] == ["b"]


def test_opens_on_line_checks_first_3_seconds_for_dialogue():
    from hookline.evaluate import opens_on_line

    show = load_show([("1.txt", make_ep(1))])  # dialogue beat every 5 s
    assert opens_on_line(P("a", 1, 5.0, 40.0), show) is True
    assert opens_on_line(P("b", 1, 6.0, 40.0), show) is False
