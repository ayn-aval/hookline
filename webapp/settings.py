"""Sidebar model settings and the shared demo-key budget."""
from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Optional

import streamlit as st

from hookline.llm import DEFAULT_PROVIDER, PROVIDERS, SUGGESTED_MODELS, LLMConfig

# The shared demo key is on Gemini's free tier (about 20 requests per model per day), so the
# budget is global across all visitors, not per browser session.
DEMO_RUNS_PER_DAY = 3
DEMO_MAX_EPISODES = 10
OTHER_MODEL = "Other (type a name)"


@dataclass
class DemoBudget:
    runs_per_day: int
    _used: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def remaining(self) -> int:
        with self._lock:
            return self.runs_per_day - self._used.get(dt.date.today(), 0)

    def consume(self) -> None:
        with self._lock:
            today = dt.date.today()
            self._used = {today: self._used.get(today, 0) + 1}


@st.cache_resource
def demo_budget() -> DemoBudget:
    return DemoBudget(DEMO_RUNS_PER_DAY)


@dataclass
class ModelChoice:
    config: LLMConfig
    judge_config: LLMConfig
    using_demo_key: bool


def _secret(name: str) -> Optional[str]:
    try:
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001 - running without a secrets file is fine
        return None


def _model_picker(label: str, provider: str, default: str, disabled: bool, help: Optional[str] = None) -> str:
    """Pick from known model names to avoid typos; 'Other' still allows any name the provider serves."""
    options = list(SUGGESTED_MODELS.get(provider, []))
    if not options:
        return st.sidebar.text_input(label, value=default, disabled=disabled, help=help).strip()
    if default not in options:
        options.insert(0, default)
    choice = st.sidebar.selectbox(label, options + [OTHER_MODEL], index=options.index(default),
                                  disabled=disabled, help=help, key=f"{label}-{provider}")
    if choice != OTHER_MODEL:
        return choice
    return st.sidebar.text_input(f"{label} name", disabled=disabled, key=f"{label}-{provider}-typed",
                                 help="Exact model ID as the provider lists it.").strip()


def model_sidebar() -> ModelChoice:
    st.sidebar.header("Model")
    key = st.sidebar.text_input("API key", type="password",
                                help="Your own key for the chosen provider. Leave empty to use the demo key.")
    demo_key = _secret("GEMINI_API_KEY")
    using_demo = not key and bool(demo_key)
    providers = list(PROVIDERS)
    provider = st.sidebar.selectbox("Provider", providers, index=providers.index(DEFAULT_PROVIDER),
                                    disabled=using_demo,
                                    help="Any OpenAI-compatible API. Use 'custom' for your own endpoint.")
    preset = PROVIDERS[provider]
    model = _model_picker("Model", provider, preset["default_model"], using_demo,
                          help="Finds the promos.")
    judge_model = _model_picker("Judge model", provider, preset.get("judge_model") or preset["default_model"],
                                using_demo, help="Scores the promos. A different model avoids grading its own picks.")
    base_url = st.sidebar.text_input("Base URL", value=preset["base_url"]) if provider == "custom" else None
    if using_demo:
        st.sidebar.caption(f"Using the shared free-tier demo key: {demo_budget().remaining()} of "
                           f"{DEMO_RUNS_PER_DAY} runs left today, up to {DEMO_MAX_EPISODES} episodes each. "
                           "Add your own key for full shows or other models.")
        provider, model, judge_model = DEFAULT_PROVIDER, PROVIDERS[DEFAULT_PROVIDER]["default_model"], \
            PROVIDERS[DEFAULT_PROVIDER]["judge_model"]
    elif not key:
        st.sidebar.caption("Enter an API key to run on a new show.")
    api_key = key or (demo_key if using_demo else None)
    config = LLMConfig(provider=provider, model=model or None, api_key=api_key, base_url=base_url)
    judge_config = LLMConfig(provider=provider, model=judge_model or model or None, api_key=api_key,
                             base_url=base_url)
    return ModelChoice(config=config, judge_config=judge_config, using_demo_key=using_demo)
