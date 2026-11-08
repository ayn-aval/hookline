from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "outputs" / "i-married-a-broken-soldier" / "promos.json"


def test_app_loads_without_errors():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Hookline"
    assert len(at.tabs) == 4


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample run not generated yet")
def test_app_shows_ranked_sample_promos():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert any("#1 ·" in m.value for m in at.markdown)


def test_demo_budget_is_shared_and_daily():
    from webapp.settings import DemoBudget

    budget = DemoBudget(runs_per_day=2)
    budget.consume()
    assert budget.remaining() == 1
    budget.consume()
    assert budget.remaining() == 0


def test_demo_key_locks_model_fields():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    at.secrets["GEMINI_API_KEY"] = "demo"
    at.run()
    assert not at.exception
    model = next(t for t in at.sidebar.selectbox if t.label == "Model")
    assert model.disabled and model.value == "gemini-3.5-flash-lite"


def test_model_is_picked_from_a_list_with_a_typed_fallback():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    model = next(s for s in at.sidebar.selectbox if s.label == "Model")
    assert "gemini-3.5-flash" in model.options and model.options[-1].startswith("Other")
    assert not any(t.label == "Model name" for t in at.sidebar.text_input)
    model.select(model.options[-1]).run()
    typed = next(t for t in at.sidebar.text_input if t.label == "Model name")
    typed.input("gemini-3.8-flash").run()
    assert not at.exception


def test_background_job_keeps_result_in_session_state(monkeypatch):
    import time as _time

    import streamlit as st

    from hookline.llm import LLMConfig
    from hookline.parse import load_show
    from hookline.schemas import RunResult
    from webapp import views
    from webapp.settings import ModelChoice

    from .test_pipeline import make_ep

    monkeypatch.setattr(views, "run_pipeline", lambda show, llm, judge_llm, progress: RunResult([], {}, {"ok": 1}))
    cfg = LLMConfig(provider="gemini", model="m", api_key="k")
    views._start_job(load_show([("1.txt", make_ep(1))]), ModelChoice(cfg, cfg, using_demo_key=False))
    state = st.session_state[views.JOB_KEY]
    deadline = _time.time() + 5
    while not state["done"] and _time.time() < deadline:
        _time.sleep(0.05)
    assert state["done"] and state["error"] is None and state["result"].meta == {"ok": 1}
