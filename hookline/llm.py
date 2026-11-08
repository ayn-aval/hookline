"""Thin, swappable LLM client.

Every provider we care about speaks the OpenAI chat-completions protocol, so swapping
models is one setting: provider preset (base URL) + model name + key. Every call is
cached on disk (the cache doubles as the "raw outputs" folder) so re-runs are free.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

PROVIDERS: dict[str, dict] = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "default_model": "gemini-3.5-flash", "key_env": "GEMINI_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1/", "default_model": "gpt-5-mini", "key_env": "OPENAI_API_KEY"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1/", "default_model": "claude-sonnet-5-5",
                  "key_env": "ANTHROPIC_API_KEY"},
    "groq": {"base_url": "https://api.groq.com/openai/v1/", "default_model": "llama-3.3-70b-versatile",
             "key_env": "GROQ_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1/", "default_model": "openrouter/auto",
                   "key_env": "OPENROUTER_API_KEY"},
    "ollama": {"base_url": "http://localhost:11434/v1/", "default_model": "qwen3:8b", "key_env": "OLLAMA_API_KEY"},
    "custom": {"base_url": "http://localhost:8000/v1/", "default_model": "", "key_env": "HOOKLINE_API_KEY"},
}


@dataclass
class LLMConfig:
    provider: str = "gemini"
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.4

    def __post_init__(self):
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown provider {self.provider!r}; choose from {sorted(PROVIDERS)}")
        if not self.model:
            self.model = PROVIDERS[self.provider]["default_model"]

    def resolved_base_url(self) -> str:
        return self.base_url or PROVIDERS[self.provider]["base_url"]

    def resolved_key(self) -> str:
        return (self.api_key or os.getenv("HOOKLINE_API_KEY")
                or os.getenv(PROVIDERS[self.provider]["key_env"]) or "none")

    @classmethod
    def from_env(cls, **overrides) -> "LLMConfig":
        kw = dict(
            provider=os.getenv("HOOKLINE_PROVIDER", "gemini"),
            model=os.getenv("HOOKLINE_MODEL") or None,
            api_key=os.getenv("HOOKLINE_API_KEY") or None,
            base_url=os.getenv("HOOKLINE_BASE_URL") or None,
        )
        kw.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**kw)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json_text(text: str):
    """Parse JSON from a model reply, tolerating code fences and chatter around it."""
    t = _FENCE.sub("", (text or "").strip()).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if starts:
        s = min(starts)
        e = max(t.rfind("}"), t.rfind("]"))
        if e > s:
            return json.loads(t[s:e + 1])
    raise json.JSONDecodeError("no JSON object found", t, 0)


class LLMError(RuntimeError):
    pass


@dataclass
class LLM:
    cfg: LLMConfig
    cache_dir: Optional[Path] = None
    client: object = None
    max_retries: int = 6
    usage: dict = field(default_factory=lambda: {"calls": 0, "cached": 0, "prompt_tokens": 0,
                                                 "completion_tokens": 0, "retries": 0})

    def __post_init__(self):
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(base_url=self.cfg.resolved_base_url(), api_key=self.cfg.resolved_key(),
                                 timeout=180, max_retries=0)
        if self.cache_dir:
            self.cache_dir = Path(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # -- cache -------------------------------------------------------------------------
    def _key(self, messages) -> str:
        blob = json.dumps({"model": self.cfg.model, "t": self.cfg.temperature, "m": messages}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def _cache_path(self, tag: str, key: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", tag)
        return self.cache_dir / f"{safe}__{key}.json"

    # -- calls -------------------------------------------------------------------------
    def _bump(self, **kw):
        with self._lock:
            for k, v in kw.items():
                self.usage[k] = self.usage.get(k, 0) + v

    def _complete(self, messages) -> tuple[str, dict]:
        delay = 2.0
        use_json_mode = True
        for attempt in range(self.max_retries + 1):
            try:
                kw = dict(model=self.cfg.model, messages=messages, temperature=self.cfg.temperature)
                if use_json_mode:
                    kw["response_format"] = {"type": "json_object"}
                r = self.client.chat.completions.create(**kw)
                text = r.choices[0].message.content or ""
                u = getattr(r, "usage", None)
                usage = {"prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                         "completion_tokens": getattr(u, "completion_tokens", 0) or 0}
                return text, usage
            except Exception as e:  # noqa: BLE001 — provider SDK errors vary
                status = getattr(e, "status_code", None)
                msg = str(e)
                if status == 400 and use_json_mode and "response_format" in msg.lower():
                    use_json_mode = False  # provider doesn't support JSON mode; rely on prompt
                    continue
                retryable = status in (408, 409, 429, 500, 502, 503, 504) or status is None
                if not retryable or attempt == self.max_retries:
                    raise LLMError(f"{self.cfg.provider}/{self.cfg.model} failed: {msg[:300]}") from e
                self._bump(retries=1)
                time.sleep(delay + random.random())
                delay = min(delay * 2, 60)
        raise LLMError("unreachable")

    def json(self, system: str, user: str, tag: str):
        """Call the model and return parsed JSON. Cached by (model, temperature, messages)."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        key = self._key(messages)
        path = self._cache_path(tag, key)
        if path and path.exists():
            rec = json.loads(path.read_text())
            self._bump(cached=1)
            return rec["parsed"]
        text, usage = self._complete(messages)
        self._bump(calls=1, **usage)
        try:
            parsed = parse_json_text(text)
        except json.JSONDecodeError as err:
            repair = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"Your reply was not valid JSON ({err}). "
                                            "Reply again with ONLY the corrected JSON object."},
            ]
            text, usage = self._complete(repair)
            self._bump(calls=1, **usage)
            parsed = parse_json_text(text)  # second failure propagates to the caller
        if path:
            path.write_text(json.dumps({"tag": tag, "provider": self.cfg.provider, "model": self.cfg.model,
                                        "temperature": self.cfg.temperature, "ts": time.time(),
                                        "request": messages, "response_text": text, "parsed": parsed,
                                        "usage": usage}, indent=1, ensure_ascii=False))
        return parsed
