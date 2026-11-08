"""Cached, retrying JSON client over any OpenAI-compatible endpoint.

Each call is cached on disk under ``cache_dir``. The cache doubles as the run's raw-output
record, so it stores the model's reply but never the (confidential) user prompt.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .jsonparse import parse_json_text
from .providers import LLMConfig

RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}
DAILY_QUOTA_MARKERS = ("per day", "perday")


class LLMError(RuntimeError):
    pass


def _empty_usage() -> dict:
    return {"calls": 0, "cached": 0, "prompt_tokens": 0, "completion_tokens": 0, "retries": 0}


@dataclass
class LLM:
    cfg: LLMConfig
    cache_dir: Optional[Path] = None
    client: object = None
    max_retries: int = 6
    usage: dict = field(default_factory=_empty_usage)

    def __post_init__(self) -> None:
        self._quota_error: Optional[str] = None
        if self.client is None:
            from openai import OpenAI

            self.client = OpenAI(base_url=self.cfg.resolved_base_url(), api_key=self.cfg.resolved_key(),
                                 timeout=180, max_retries=0)
        if self.cache_dir:
            self.cache_dir = Path(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def json(self, system: str, user: str, tag: str):
        """Return the model's reply parsed as JSON, from cache when available."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        path = self._cache_path(tag, self._cache_key(messages))
        if path and path.exists():
            record = json.loads(path.read_text())
            usage = record.get("usage") or {}
            self._bump(cached=1, prompt_tokens=usage.get("prompt_tokens", 0),
                       completion_tokens=usage.get("completion_tokens", 0))
            return record["parsed"]

        text, usage = self._complete(messages)
        try:
            parsed = parse_json_text(text)
        except json.JSONDecodeError as err:
            repair = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"Your reply was not valid JSON ({err}). "
                                            "Reply again with ONLY the corrected JSON object."},
            ]
            text, usage = self._complete(repair)
            parsed = parse_json_text(text)

        if path:
            record = {
                "tag": tag, "provider": self.cfg.provider, "model": self.cfg.model,
                "temperature": self.cfg.temperature, "ts": time.time(),
                "system_prompt": system, "user_chars": len(user),
                "user_sha256": hashlib.sha256(user.encode()).hexdigest(),
                "response_text": text, "parsed": parsed, "usage": usage,
            }
            path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
        return parsed

    def _cache_key(self, messages: list[dict]) -> str:
        blob = json.dumps({"model": self.cfg.model, "t": self.cfg.temperature, "m": messages}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()[:12]

    def _cache_path(self, tag: str, key: str) -> Optional[Path]:
        if not self.cache_dir:
            return None
        safe_tag = re.sub(r"[^A-Za-z0-9_.-]", "_", tag)
        return self.cache_dir / f"{safe_tag}__{key}.json"

    def _bump(self, **counts: int) -> None:
        with self._lock:
            for k, v in counts.items():
                self.usage[k] = self.usage.get(k, 0) + v

    def _complete(self, messages: list[dict]) -> tuple[str, dict]:
        if self._quota_error:
            raise LLMError(self._quota_error)
        delay = 2.0
        json_mode = True
        for attempt in range(self.max_retries + 1):
            try:
                kwargs = dict(model=self.cfg.model, messages=messages, temperature=self.cfg.temperature)
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                reply = self.client.chat.completions.create(**kwargs)
            except Exception as exc:  # noqa: BLE001 - provider SDK errors vary by vendor
                status = getattr(exc, "status_code", None)
                if status == 400 and json_mode and "response_format" in str(exc).lower():
                    json_mode = False  # provider lacks JSON mode; the prompt still asks for JSON
                    continue
                if status == 429 and any(m in str(exc).lower() for m in DAILY_QUOTA_MARKERS):
                    self._quota_error = (f"{self.cfg.provider}/{self.cfg.model}: daily quota exhausted; "
                                         "switch model or provider, or wait for the quota to reset")
                    raise LLMError(self._quota_error) from exc
                retryable = status in RETRYABLE_STATUS or status is None
                if not retryable or attempt == self.max_retries:
                    raise LLMError(f"{self.cfg.provider}/{self.cfg.model} failed: {str(exc)[:300]}") from exc
                self._bump(retries=1)
                time.sleep(delay + random.random())
                delay = min(delay * 2, 60)
                continue
            usage_obj = getattr(reply, "usage", None)
            usage = {"prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                     "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0}
            self._bump(calls=1, **usage)
            return reply.choices[0].message.content or "", usage
        raise LLMError(f"{self.cfg.provider}/{self.cfg.model}: retries exhausted")
