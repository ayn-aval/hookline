"""The app's tabs: sample results, run on a new show, quality, how it works."""
from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

import streamlit as st

from hookline.llm import LLM
from hookline.parse import load_show, zip_to_pairs
from hookline.pipeline import RunResult, run_pipeline
from hookline.report import load_run, promo_dict, promos_csv, write_report

from .components import approved_export, filter_promos, promo_card, run_summary
from .settings import DEMO_MAX_EPISODES, DEMO_RUNS_PER_SESSION, ModelChoice

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RUN = ROOT / "outputs" / "i-married-a-broken-soldier"
EVAL_DIR = ROOT / "eval"


def sample_results() -> None:
    st.subheader("I Married a Broken Soldier. He was a Duke — 50 episodes")
    if not (SAMPLE_RUN / "promos.json").exists():
        st.info("No committed sample run found.")
        return
    promos, bible, meta = load_run(SAMPLE_RUN)
    st.markdown(f"**Premise (series bible):** {bible.get('show_premise', '')}")
    run_summary(meta)
    st.caption("Script lines are not shown here: the screenplays are confidential and are not published with "
               "this demo. Upload scripts under 'Run on a new show' to see each promo's lines.")
    shown = filter_promos(promos, key="sample")
    approved_export(promos, key="sample", file_name="approved_promos.csv")
    for p in shown:
        promo_card(p, key="sample")


def _uploaded_pairs(files) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for f in files:
        data = f.getvalue()
        if f.name.lower().endswith(".zip"):
            pairs += zip_to_pairs(data)
        else:
            pairs.append((f.name, data.decode("utf-8", "replace")))
    return pairs


def _run_in_background(show, llm, progress_bar) -> RunResult:
    """Run the pipeline off the script thread and poll its progress (Streamlit calls must stay on this thread)."""
    state = {"message": "Starting", "fraction": 0.0, "result": None, "error": None}

    def report(message: str, fraction: float) -> None:
        state["message"], state["fraction"] = message, fraction

    def work() -> None:
        try:
            state["result"] = run_pipeline(show, llm, progress=report)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user below
            state["error"] = exc

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    while worker.is_alive():
        progress_bar.progress(min(1.0, state["fraction"]), text=state["message"])
        time.sleep(0.5)
    progress_bar.progress(1.0, text="Done" if not state["error"] else "Failed")
    if state["error"]:
        raise state["error"]
    return state["result"]


def new_show(choice: ModelChoice) -> None:
    st.subheader("Run on a new show")
    st.markdown("Upload episode screenplays (`.txt` files or one `.zip`) in the same timestamped format. "
                "Results stay in this browser session.")
    files = st.file_uploader("Screenplays", type=["txt", "zip"], accept_multiple_files=True)
    if not files:
        _show_session_result()
        return
    show = load_show(_uploaded_pairs(files))
    st.write(f"Parsed **{len(show.episodes)} episodes** and "
             f"**{sum(len(e.beats) for e in show.episodes)} beats**.")
    for warning in show.warnings[:20]:
        st.warning(warning)
    runs = st.session_state.get("demo_runs", 0)
    blocked = choice.using_demo_key and (runs >= DEMO_RUNS_PER_SESSION or len(show.episodes) > DEMO_MAX_EPISODES)
    if not choice.config.api_key:
        st.info("Add an API key in the sidebar to run.")
    elif blocked:
        st.warning("The shared demo key's limit for this session is reached. Add your own key in the sidebar.")
    elif show.episodes and st.button("Find promos", type="primary"):
        if choice.using_demo_key:
            st.session_state["demo_runs"] = runs + 1
        cache = Path(tempfile.mkdtemp(prefix="hookline-"))
        try:
            result = _run_in_background(show, LLM(choice.config, cache_dir=cache), st.progress(0.0))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Run failed: {exc}")
            return
        st.session_state["session_result"] = (result, show)
    _show_session_result()


def _show_session_result() -> None:
    if "session_result" not in st.session_state:
        return
    result, show = st.session_state["session_result"]
    run_summary(result.meta)
    with tempfile.TemporaryDirectory() as tmp:
        report_path = Path(tmp) / "report.md"
        write_report(result.promos, result.bible, result.meta, report_path)
        report_md = report_path.read_text()
    cols = st.columns(3)
    cols[0].download_button("promos.json", json.dumps({"bible": result.bible, "meta": result.meta,
                                                        "promos": [promo_dict(p) for p in result.promos]},
                                                       indent=1, ensure_ascii=False), file_name="promos.json")
    cols[1].download_button("promos.csv", promos_csv(result.promos), file_name="promos.csv")
    cols[2].download_button("report.md", report_md, file_name="report.md")
    approved_export(result.promos, key="session", file_name="approved_promos.csv")
    for p in filter_promos(result.promos, key="session"):
        promo_card(p, key="session", show=show)


def quality() -> None:
    st.subheader("How we know it is good, and where it fails")
    for name in ("results.md", "spot_check.md"):
        path = EVAL_DIR / name
        if path.exists():
            st.markdown(path.read_text())
    if not (EVAL_DIR / "results.md").exists():
        st.info("Evaluation results are not available yet.")


def how_it_works() -> None:
    st.subheader("How it works")
    st.markdown(
        """
1. **Parse (code).** Each screenplay becomes timestamped *beats* (camera, action, dialogue, sound) with stable IDs.
2. **Series bible (LLM, 1 call).** Characters, aliases, arcs and which twists must not be spoiled.
3. **Mine each episode (LLM, 1 call per episode).** 2-4 continuous promo windows plus standout hook/cliffhanger moments, referenced by beat ID only.
4. **Stitch (LLM, 1 call).** 2-3 moments joined into one promo, across episodes if useful.
5. **Validate (code).** Beat IDs become real timestamps; 20-60 s, hook within 3 s, ends on the cliffhanger, never cuts a line mid-sentence; duplicates removed.
6. **Cold-viewer judge (LLM).** Scores each clip seeing only its own lines, like a stranger scrolling.
7. **Rank (code).** Weighted score, spoiler penalty, early-episode preference, no back-to-back promos from one episode.

The model is one setting: any OpenAI-compatible provider works (sidebar). An editor reviews the ranked list,
approves promos and exports them; nothing is posted automatically.
"""
    )
