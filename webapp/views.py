"""The app's tabs: sample results, run on a new show, quality, how it works."""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import time
from pathlib import Path

import streamlit as st

from hookline.llm import LLM
from hookline.parse import load_show, zip_to_pairs
from hookline.pipeline import run_pipeline
from hookline.report import load_run, promos_csv, promos_payload, report_markdown
from hookline.schemas import ParseResult

from .components import approved_export, filter_promos, promo_card, run_summary
from .settings import DEMO_MAX_EPISODES, ModelChoice, demo_budget

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RUN = ROOT / "outputs" / "i-married-a-broken-soldier"
EVAL_DIR = ROOT / "eval"
CACHE_ROOT = Path(tempfile.gettempdir()) / "hookline-cache"
RAW_OUTPUTS_URL = "https://github.com/ayn-aval/hookline/tree/main/outputs/i-married-a-broken-soldier"
JOB_KEY = "run_job"


def sample_results() -> None:
    st.subheader("I Married a Broken Soldier. He was a Duke — 50 episodes")
    if not (SAMPLE_RUN / "promos.json").exists():
        st.info("No committed sample run found.")
        return
    promos, bible, meta = load_run(SAMPLE_RUN)
    st.markdown(f"**Premise (series bible):** {bible.get('show_premise', '')}")
    run_summary(meta)
    st.caption("Script lines are not shown here: the screenplays are confidential and are not published with "
               "this demo. Upload scripts under 'Run on a new show' to see each promo's lines. "
               f"Unedited raw outputs of this run: [GitHub folder]({RAW_OUTPUTS_URL}).")
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


def _show_key(show: ParseResult) -> str:
    """Stable fingerprint of the uploaded scripts, so retries reuse the same LLM cache."""
    return hashlib.sha256(show.model_dump_json().encode()).hexdigest()[:16]


def _start_job(show: ParseResult, choice: ModelChoice) -> None:
    """Run the pipeline on a worker thread whose state lives in the session, so reruns don't lose it."""
    cache = CACHE_ROOT / _show_key(show)
    state = {"message": "Starting", "fraction": 0.0, "result": None, "error": None, "done": False,
             "demo": choice.using_demo_key, "show": show, "run_id": time.time_ns()}

    def report(message: str, fraction: float) -> None:
        state["message"], state["fraction"] = message, fraction

    def work() -> None:
        try:
            state["result"] = run_pipeline(show, LLM(choice.config, cache_dir=cache),
                                           judge_llm=LLM(choice.judge_config, cache_dir=cache), progress=report)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            state["error"] = exc
        state["done"] = True

    threading.Thread(target=work, daemon=True).start()
    st.session_state[JOB_KEY] = state


def _follow_job() -> None:
    state = st.session_state.get(JOB_KEY)
    if not state or state.get("reported"):
        return
    bar = st.progress(0.0)
    while not state["done"]:
        bar.progress(min(1.0, state["fraction"]), text=state["message"])
        time.sleep(0.5)
    state["reported"] = True
    if state["error"] is not None:
        bar.progress(1.0, text="Failed")
        st.error(f"Run failed: {state['error']}")
        return
    bar.progress(1.0, text="Done")
    if state["demo"]:
        demo_budget().consume()


def new_show(choice: ModelChoice) -> None:
    st.subheader("Run on a new show")
    st.markdown("Upload episode screenplays (`.txt` files or one `.zip`) in the same timestamped format. "
                "Results stay in this browser session.")
    files = st.file_uploader("Screenplays", type=["txt", "zip"], accept_multiple_files=True)
    job = st.session_state.get(JOB_KEY)
    running = bool(job and not job["done"])
    if files and not running:
        try:
            show = load_show(_uploaded_pairs(files))
        except ValueError as exc:
            st.error(f"Could not read the upload: {exc}")
            return
        st.write(f"Parsed **{len(show.episodes)} episodes** and "
                 f"**{sum(len(e.beats) for e in show.episodes)} beats**.")
        for warning in show.warnings[:20]:
            st.warning(warning)
        if not choice.config.api_key:
            st.info("Add an API key in the sidebar to run.")
        elif choice.using_demo_key and demo_budget().remaining() <= 0:
            st.warning("The shared demo key has no runs left today. Add your own key in the sidebar.")
        elif choice.using_demo_key and len(show.episodes) > DEMO_MAX_EPISODES:
            st.warning(f"The demo key handles up to {DEMO_MAX_EPISODES} episodes. Upload fewer, or add your own key.")
        elif show.episodes and st.button("Find promos", type="primary"):
            _start_job(show, choice)
    _follow_job()
    _show_session_result()


def _show_session_result() -> None:
    state = st.session_state.get(JOB_KEY)
    if not state or not state.get("done") or state["result"] is None:
        return
    result, show, key = state["result"], state["show"], f"session-{state['run_id']}"
    run_summary(result.meta)
    cols = st.columns(3)
    cols[0].download_button("promos.json", json.dumps(promos_payload(result), indent=1, ensure_ascii=False),
                            file_name="promos.json")
    cols[1].download_button("promos.csv", promos_csv(result.promos), file_name="promos.csv")
    cols[2].download_button("report.md", report_markdown(result.promos, result.bible, result.meta),
                            file_name="report.md")
    approved_export(result.promos, key=key, file_name="approved_promos.csv")
    for p in filter_promos(result.promos, key=key):
        promo_card(p, key=key, show=show)


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
3. **Mine (LLM, 1 call per 5 episodes by default).** 2-4 continuous promo windows per episode plus standout hook and cliffhanger moments, referenced by beat ID only.
4. **Stitch (LLM, 1 call).** 2-3 moments joined into one promo, across episodes if useful.
5. **Validate (code).** Beat IDs become real timestamps; 20-60 s, hook within 3 s, ends on the cliffhanger, never cuts a line mid-sentence. Over-long windows are condensed, short ones get a longer run-up, and duplicates are removed.
6. **Cold-viewer judge (LLM, a different model).** Scores each clip seeing only its own lines, like a stranger scrolling.
7. **Rank (code).** Weighted score, spoiler penalty, early-episode preference, no back-to-back promos from one episode.

The model is one setting: any OpenAI-compatible provider works (sidebar). An editor reviews the ranked list,
approves promos and exports them; nothing is posted automatically.
"""
    )
