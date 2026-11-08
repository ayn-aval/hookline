"""Hookline web app (Streamlit entry point)."""
import streamlit as st

from webapp.settings import model_sidebar
from webapp.views import how_it_works, new_show, quality, sample_results

st.set_page_config(page_title="Hookline · promo finder", layout="wide")
st.title("Hookline")
st.caption("Finds ready-to-cut promos in microdrama screenplays: hook in the first 3 seconds, "
           "cliffhanger at the end, 20-60 seconds, ranked for posting.")

choice = model_sidebar()
tabs = st.tabs(["Ranked promos (sample show)", "Run on a new show", "Quality", "How it works"])
with tabs[0]:
    sample_results()
with tabs[1]:
    new_show(choice)
with tabs[2]:
    quality()
with tabs[3]:
    how_it_works()
