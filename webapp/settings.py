"""Sidebar model settings and the shared demo-key policy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import streamlit as st

from hookline.llm import DEFAULT_PROVIDER, PROVIDERS, LLMConfig

# The shared demo key is on Gemini's free tier (about 20 requests per model per day).
DEMO_RUNS_PER_SESSION = 2
DEMO_MAX_EPISODES = 10


@dataclass
class ModelChoice:
    config: LLMConfig
    judge_config: LLMConfig
    using_demo_key: bool


def _secret(name: str) -> Optional[str]:
    try:
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001 - no secrets file locally is fine
        return None


def model_sidebar() -> ModelChoice:
    st.sidebar.header("Model")
    providers = list(PROVIDERS)
    provider = st.sidebar.selectbox("Provider", providers, index=providers.index(DEFAULT_PROVIDER),
                                    help="Any OpenAI-compatible API. Use 'custom' for your own endpoint.")
    model = st.sidebar.text_input("Model", value=PROVIDERS[provider]["default_model"])
    judge_model = st.sidebar.text_input("Judge model", value=PROVIDERS[provider].get("judge_model") or model,
                                        help="Scores the promos. A different model avoids grading its own picks.")
    base_url = None
    if provider == "custom":
        base_url = st.sidebar.text_input("Base URL", value=PROVIDERS["custom"]["base_url"])
    key = st.sidebar.text_input("API key", type="password",
                                help="Leave empty to use the demo Gemini key (limited runs per session).")
    demo_key = _secret("GEMINI_API_KEY") if provider == "gemini" else None
    using_demo = not key and bool(demo_key)
    if using_demo:
        st.sidebar.caption(f"Using the shared free-tier demo key: up to {DEMO_RUNS_PER_SESSION} runs of "
                           f"{DEMO_MAX_EPISODES} episodes per session. Add your own key for full shows.")
    elif not key:
        st.sidebar.caption("Enter an API key to run on a new show.")
    config = LLMConfig(provider=provider, model=model or None, api_key=key or demo_key, base_url=base_url)
    judge_config = LLMConfig(provider=provider, model=judge_model or model or None, api_key=key or demo_key,
                             base_url=base_url)
    return ModelChoice(config=config, judge_config=judge_config, using_demo_key=using_demo)
