from types import SimpleNamespace

from hookline.llm import LLM, LLMConfig, PROVIDERS, parse_json_text


class FakeClient:
    """Mimics openai.OpenAI().chat.completions.create, replying from a queue."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        text = self.replies.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def cfg():
    return LLMConfig(provider="gemini", model="m", api_key="k")


def test_cache_hit_skips_call(tmp_path):
    fake = FakeClient(['{"a": 1}'])
    llm = LLM(cfg(), cache_dir=tmp_path, client=fake)
    assert llm.json("sys", "user", tag="t") == {"a": 1}
    llm2 = LLM(cfg(), cache_dir=tmp_path, client=fake)
    assert llm2.json("sys", "user", tag="t") == {"a": 1}
    assert len(fake.calls) == 1
    assert llm2.usage["cached"] == 1
    assert list(tmp_path.glob("t__*.json"))


def test_json_repair_retry(tmp_path):
    fake = FakeClient(["not json at all", '{"ok": true}'])
    llm = LLM(cfg(), cache_dir=tmp_path, client=fake)
    assert llm.json("sys", "user", tag="t") == {"ok": True}
    assert len(fake.calls) == 2
    assert "not valid JSON" in fake.calls[1]["messages"][-1]["content"]


def test_strip_code_fences():
    assert parse_json_text('```json\n{"x": [1, 2]}\n```') == {"x": [1, 2]}
    assert parse_json_text('Sure! {"x": 1} hope that helps') == {"x": 1}


def test_providers_have_base_urls():
    for name in ["gemini", "openai", "anthropic", "groq", "openrouter", "ollama"]:
        assert PROVIDERS[name]["base_url"].startswith("http")
    assert LLMConfig(provider="gemini").model == "gemini-3.5-flash-lite"


def test_from_env(monkeypatch):
    monkeypatch.setenv("HOOKLINE_PROVIDER", "groq")
    monkeypatch.setenv("HOOKLINE_MODEL", "llama-x")
    monkeypatch.setenv("HOOKLINE_API_KEY", "abc")
    c = LLMConfig.from_env()
    assert (c.provider, c.model, c.api_key) == ("groq", "llama-x", "abc")
    assert c.resolved_base_url() == PROVIDERS["groq"]["base_url"]


def test_cache_file_never_stores_user_content(tmp_path):
    """raw/ is published as 'raw outputs'; it must not leak the confidential screenplay we sent."""
    fake = FakeClient(['{"a": 1}'])
    llm = LLM(cfg(), cache_dir=tmp_path, client=fake)
    llm.json("system prompt", "SECRET SCREENPLAY LINE", tag="t")
    blob = next(tmp_path.glob("t__*.json")).read_text()
    assert "SECRET SCREENPLAY LINE" not in blob
    assert '"response_text"' in blob


class QuotaError(Exception):
    status_code = 429


class DailyQuotaClient(FakeClient):
    def _create(self, **kw):
        self.calls.append(kw)
        raise QuotaError("Quota exceeded: Generate content requests per day limit exceeded on Free Tier")


def test_daily_quota_fails_fast_without_retrying(tmp_path):
    import pytest

    from hookline.llm import LLMError

    fake = DailyQuotaClient([])
    llm = LLM(cfg(), cache_dir=tmp_path, client=fake)
    with pytest.raises(LLMError, match="daily quota"):
        llm.json("s", "u", tag="t")
    assert len(fake.calls) == 1


def test_cached_calls_still_count_tokens_for_cost(tmp_path):
    fake = FakeClient(['{"a": 1}'])
    LLM(cfg(), cache_dir=tmp_path, client=fake).json("s", "u", tag="t")
    again = LLM(cfg(), cache_dir=tmp_path, client=fake)
    again.json("s", "u", tag="t")
    assert again.usage["calls"] == 0 and again.usage["cached"] == 1
    assert again.usage["prompt_tokens"] == 10 and again.usage["completion_tokens"] == 5


class StatusError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FailingClient(FakeClient):
    def __init__(self, exc):
        super().__init__([])
        self.exc = exc

    def _create(self, **kw):
        self.calls.append(kw)
        raise self.exc


def test_unknown_model_fails_fast_with_a_clear_message():
    import pytest

    from hookline.llm import LLMError

    fake = FailingClient(StatusError(404, "models/gemni-flash is not found for API version v1beta"))
    llm = LLM(LLMConfig(provider="gemini", model="gemni-flash", api_key="k"), client=fake)
    with pytest.raises(LLMError, match="model 'gemni-flash' was not found"):
        llm.json("sys", "user", tag="t")
    assert len(fake.calls) == 1


def test_rejected_key_gets_a_clear_message():
    import pytest

    from hookline.llm import LLMError

    llm = LLM(cfg(), client=FailingClient(StatusError(401, "API key not valid")))
    with pytest.raises(LLMError, match="API key was rejected"):
        llm.json("sys", "user", tag="t")


def test_every_provider_suggests_its_default_model():
    from hookline.llm import SUGGESTED_MODELS

    for name, preset in PROVIDERS.items():
        if preset["default_model"]:
            assert SUGGESTED_MODELS[name][0] == preset["default_model"]
    assert PROVIDERS["gemini"]["judge_model"] in SUGGESTED_MODELS["gemini"]
