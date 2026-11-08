"""Lenient JSON extraction from model replies."""
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json_text(text: str):
    """Parse JSON from a reply, tolerating code fences and prose around the object."""
    cleaned = _FENCE.sub("", (text or "").strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if starts:
        start = min(starts)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end > start:
            return json.loads(cleaned[start:end + 1])
    raise json.JSONDecodeError("no JSON object found", cleaned, 0)
