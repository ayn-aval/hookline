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
    write_outputs(run_pipeline(show, llm, max_workers=1), show, tmp_path)
    report = evaluate(tmp_path, show, llm, alt_llm=FakeLLM(), eval_dir=tmp_path / "eval", workers=1)
    data = json.loads((tmp_path / "eval" / "results.json").read_text())
    assert data["baseline"]["n"] == 2
    assert set(data["baseline"]["mean"]) >= {"hook", "cliff", "standalone", "emotion", "weighted"}
    assert data["stability"]["top10_refound"] == 1.0
    assert data["constraints"]["final"] == 3
    assert "Baseline" in report["summary"]
    assert (tmp_path / "eval" / "results.md").exists()
