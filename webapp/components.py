"""Reusable rendering pieces: promo cards, run summary, approve/export controls."""
from __future__ import annotations

from typing import Optional

import pandas as pd
import streamlit as st

from hookline.parse import fmt_ts
from hookline.render import clip_block
from hookline.report import promos_csv
from hookline.schemas import ParseResult, Promo

SCORE_LABELS = {"hook": "Hook", "cliff": "Cliffhanger", "standalone": "Standalone", "emotion": "Emotion"}


def run_summary(meta: dict) -> None:
    c = meta.get("candidates", {})
    usage = meta.get("llm_usage", {})
    cols = st.columns(5)
    cols[0].metric("Promos", c.get("final", "-"))
    cols[1].metric("Episodes", len(meta.get("show_episodes", [])))
    cols[2].metric("Rejected by rules", c.get("rejected", "-"))
    cols[3].metric("LLM calls", usage.get("calls", "-"))
    cols[4].metric("Est. paid-tier cost", f"${meta.get('est_cost_usd_paid_tier', 0):.2f}")
    st.caption(f"Model `{meta.get('provider')}/{meta.get('model')}` · prompts `{meta.get('prompts_sha')}` · "
               f"{meta.get('seconds', 0):.0f}s")


def filter_promos(promos: list[Promo], key: str) -> list[Promo]:
    left, right = st.columns([2, 1])
    kinds = left.multiselect("Type", ["continuous", "stitched"], default=["continuous", "stitched"],
                             key=f"{key}-kinds")
    top = right.number_input("Show top", min_value=1, max_value=max(1, len(promos)),
                             value=min(20, max(1, len(promos))), key=f"{key}-top")
    return [p for p in promos if p.kind in kinds][: int(top)]


def _segments_table(p: Promo) -> pd.DataFrame:
    return pd.DataFrame([{"#": n, "Episode": s.ep, "Start": fmt_ts(s.start), "End": fmt_ts(s.end),
                          "Seconds": round(s.end - s.start, 1)} for n, s in enumerate(p.segments, 1)])


def promo_card(p: Promo, key: str, show: Optional[ParseResult] = None) -> None:
    with st.container(border=True):
        head, decision = st.columns([5, 1])
        head.markdown(f"**#{p.rank} · {p.title or p.id}**  \n"
                      f"{p.kind} · {p.duration:.1f}s · episodes {', '.join(map(str, p.episodes))} · "
                      f"score {p.final_score}")
        decision.checkbox("Approve", key=f"{key}-ok-{p.id}")
        st.dataframe(_segments_table(p), hide_index=True, use_container_width=True)
        st.markdown(f"**Hook:** {p.hook}  \n**Cliffhanger:** {p.cliffhanger}  \n**Why it works:** {p.why}  \n"
                    f"**Why post at #{p.rank}:** {p.post_reason}")
        scores = " · ".join(f"{label} {p.scores.get(k, '-')}/5" for k, label in SCORE_LABELS.items())
        summary = p.scores.get("cold_viewer_summary")
        weakness = p.scores.get("weakness")
        st.caption(f"Cold-viewer judge: {scores} · spoiler risk {p.spoiler}/2"
                   + (f"  \nA stranger sees: {summary}" if summary else "")
                   + (f"  \nWeakness: {weakness}" if weakness else "")
                   + (f"  \nAuto-repairs: {'; '.join(p.repairs)}" if p.repairs else ""))
        if show is not None:
            with st.expander("Script lines in this promo"):
                st.code(clip_block(p, show), language=None)


def approved_export(promos: list[Promo], key: str, file_name: str) -> None:
    approved = [p for p in promos if st.session_state.get(f"{key}-ok-{p.id}")]
    st.download_button(f"Download {len(approved)} approved promos (CSV)", promos_csv(approved),
                       file_name=file_name, mime="text/csv", disabled=not approved, key=f"{key}-approved")
