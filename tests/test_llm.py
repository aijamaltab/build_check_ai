"""ИИ-слой: клиент, кэш, повторы, GeminiPairJudge. Только фейковый transport: без сети и без ключа."""
import json

import pytest

from src.config import load_config
from src.llm import GeminiPairJudge, LlmClient, build_default_ai
from src.llm.cache import LlmCache
from src.pipeline import run_pipeline
from tests.test_generate_synthetic import gen

CFG = load_config()
LLM = CFG["rules"]["llm"]
SECRET = "AIzaFAKE-secret-key-1234567890"
GOOD = json.dumps({"same_work": True, "confidence": 0.95, "reason": "тот же бетон"})


class RateLimit(Exception):
    code = 429


class FakeTransport:
    """Отвечает по очереди: строка = текст ответа, исключение = сбой."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), 0

    def __call__(self, prompt, schema):
        self.calls += 1
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def make(tmp_path, *replies, env=None, cfg_over=None, **kw):
    llm = {**LLM, "call_pause_seconds": 0, **(cfg_over or {})}
    sleeps = []
    client = LlmClient(llm, transport=FakeTransport(*replies) if replies else None, cache=LlmCache(tmp_path / "cache"),
                       sleep=sleeps.append, env=env if env is not None else {}, **kw)
    return client, sleeps


def pair(an="Бетон М300", bn="бетонная смесь М-300", unit="m3", ak=None, bk="work"):
    a = {"name_raw": an, "name": an.lower(), "unit": unit, "kind": ak, "file": "a.xlsx", "row": 5}
    b = {"name_raw": bn, "name": bn.lower(), "unit": unit, "kind": bk, "file": "v.xlsx", "row": 7}
    return a, b


def judge(client):
    return GeminiPairJudge(client, CFG)


def test_valid_answer_is_returned_and_cached(tmp_path):
    client, _ = make(tmp_path, GOOD)
    j = judge(client)
    assert j.judge_pair(*pair())["same_work"] is True
    assert (client.stats.calls, client.stats.errors, client.stats.cache_hits) == (1, 0, 0)
    assert len(list((tmp_path / "cache").glob("*.json"))) == 1
    assert j.judge_pair(*pair())["same_work"] is True            # повтор: из кэша, API не вызывается
    assert (client._transport.calls, client.stats.cache_hits) == (1, 1)


def test_cache_record_has_model_prompt_version_time_and_no_secret(tmp_path):
    client, _ = make(tmp_path, GOOD, env={LLM["api_key_env"]: SECRET})
    judge(client).judge_pair(*pair())
    text = next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8")
    record = json.loads(text)
    assert record["model"] == LLM["model"] and record["prompt_version"] and record["created_at"] and record["answer"]
    assert SECRET not in text


def test_cache_key_ignores_case_and_spaces_but_not_unit_or_model(tmp_path):
    client, _ = make(tmp_path, GOOD)
    j = judge(client)
    j.judge_pair(*pair("Бетон М300", "бетонная смесь М-300"))
    j.judge_pair(*pair("  БЕТОН   м300 ", "Бетонная смесь м-300"))
    assert client.stats.cache_hits == 1
    j.judge_pair(*pair(unit="m2"))
    assert client.stats.calls == 2
    other, _ = make(tmp_path, GOOD, cfg_over={"model": "other-model"})
    judge(other).judge_pair(*pair())
    assert other.stats.cache_hits == 0


@pytest.mark.parametrize("bad", ["не json", "", "   ", "[]", json.dumps({"same_work": "yes", "confidence": 0.9, "reason": "x"}),
                                 json.dumps({"same_work": True, "confidence": 1.5, "reason": "x"})])
def test_bad_answer_retries_once_then_no_answer(tmp_path, bad):
    client, sleeps = make(tmp_path, bad)
    assert judge(client).judge_pair(*pair()) is None
    assert (client.stats.calls, client.stats.errors, client.stats.no_answer) == (2, 2, 1)
    assert len(sleeps) == 1 and list((tmp_path / "cache").glob("*.json")) == []   # плохой ответ не кэшируется


def test_bad_then_good_answer_succeeds_on_retry(tmp_path):
    client, _ = make(tmp_path, "не json", GOOD)
    assert judge(client).judge_pair(*pair())["same_work"] is True
    assert (client.stats.calls, client.stats.errors, client.stats.no_answer) == (2, 1, 0)


def test_429_retries_with_exponential_pause_capped_by_config(tmp_path):
    client, sleeps = make(tmp_path, RateLimit("429 RESOURCE_EXHAUSTED"), GOOD,
                          cfg_over={"max_retries": 3, "retry_pause_seconds": 2, "retry_max_pause_seconds": 3, "call_pause_seconds": 0})
    assert judge(client).judge_pair(*pair())["same_work"] is True
    client2, sleeps2 = make(tmp_path / "x", RateLimit("429"),
                            cfg_over={"max_retries": 3, "retry_pause_seconds": 2, "retry_max_pause_seconds": 3, "call_pause_seconds": 0})
    assert judge(client2).judge_pair(*pair()) is None
    assert sleeps2 == [2, 3, 3] and client2.stats.no_answer == 1          # 2, затем 4 и 8 урезаны до 3
    assert "429" in client2.last_error


def test_network_error_does_not_raise(tmp_path):
    client, _ = make(tmp_path, ConnectionError("network down"))
    assert judge(client).judge_pair(*pair()) is None
    assert client.stats.errors == 2 and client.stats.no_answer == 1


def test_pause_between_calls_uses_config(tmp_path):
    ticks = iter(range(0, 1000))
    client, sleeps = make(tmp_path, GOOD, cfg_over={"call_pause_seconds": 5}, clock=lambda: next(ticks) * 0.1)
    j = judge(client)
    j.judge_pair(*pair("Бетон М300"))
    j.judge_pair(*pair("Бетон М350"))
    assert len(sleeps) == 1 and 4 < sleeps[0] <= 5


def test_cache_only_never_calls_api_and_needs_no_key(tmp_path):
    seeded, _ = make(tmp_path, GOOD)
    judge(seeded).judge_pair(*pair())
    transport = FakeTransport(GOOD)
    client = LlmClient({**LLM, "cache_only": True}, transport=transport, cache=LlmCache(tmp_path / "cache"), env={})
    j = judge(client)
    assert j.judge_pair(*pair())["same_work"] is True                   # попадание
    assert j.judge_pair(*pair("Окна ПВХ", "Окно пластиковое")) is None   # промах = нет ответа
    assert transport.calls == 0 and client.stats.cache_hits == 1 and client.stats.no_answer == 1


def test_cache_only_env_and_availability(tmp_path):
    empty = LlmClient(LLM, cache=LlmCache(tmp_path / "e"), env={"LLM_CACHE_ONLY": "1", LLM["api_key_env"]: SECRET})
    assert empty.cache_only and not empty.available                     # режим «только кэш», кэш пуст
    seeded, _ = make(tmp_path, GOOD)
    judge(seeded).judge_pair(*pair())
    assert LlmClient(LLM, cache=LlmCache(tmp_path / "cache"), env={}).available      # нет ключа, но кэш найден
    assert LlmClient(LLM, cache=LlmCache(tmp_path / "e2"), env={LLM["api_key_env"]: SECRET}).available   # ключ есть
    assert not LlmClient(LLM, cache=LlmCache(tmp_path / "e3"), env={}).available


@pytest.mark.parametrize("a_name,b_name,unit", [
    ("Арматура А500 d12", "Арматура А500 d8", "t"),                       # числовой токен
    ("Штукатурка стен внутренняя", "Штукатурка стен наружная", "m2"),    # слова exclusive_word_groups
])
def test_answer_violating_must_match_tokens_is_rejected(tmp_path, a_name, b_name, unit):
    client, _ = make(tmp_path, GOOD)
    out = judge(client).judge_pair(*pair(a_name, b_name, unit))
    assert out["same_work"] is False and "отклонено проверкой" in out["reason"]
    assert client.stats.rejected_by_check == 1


def test_answer_with_different_unit_or_kind_is_rejected(tmp_path):
    client, _ = make(tmp_path, GOOD)
    j = judge(client)
    a, b = pair()
    b["unit"] = "m2"
    assert j.judge_pair(a, b)["same_work"] is False
    a2, b2 = pair(ak="material", bk="work")
    assert j.judge_pair(a2, b2)["same_work"] is False
    assert client.stats.rejected_by_check == 2


def test_low_confidence_means_no_decision(tmp_path):
    low = json.dumps({"same_work": True, "confidence": LLM["min_confidence"] - 0.1, "reason": "сомневаюсь"})
    client, _ = make(tmp_path, low)
    assert judge(client).judge_pair(*pair()) is None
    assert client.stats.low_confidence == 1


def test_prompt_has_names_unit_and_kind_but_no_price_or_quantity(tmp_path):
    seen = []
    client, _ = make(tmp_path, GOOD)
    client._transport = lambda prompt, schema: seen.append(prompt) or GOOD
    a, b = pair()
    a.update(quantity=123.456, unit_price=987.65)
    b.update(quantity=111.111)
    judge(client).judge_pair(a, b)
    assert "Бетон М300" in seen[0] and "m3" in seen[0] and "work" in seen[0]
    for forbidden in ("123.456", "987.65", "111.111"):
        assert forbidden not in seen[0]


def test_secret_never_appears_in_errors_stats_or_cache(tmp_path, capsys):
    client, _ = make(tmp_path, RuntimeError(f"bad request key={SECRET}"), env={LLM["api_key_env"]: SECRET})
    judge(client).judge_pair(*pair())
    shown = capsys.readouterr().out + repr(client.last_error) + repr(client.stats)
    cache_text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "cache").glob("*"))
    assert SECRET not in shown + cache_text and "***" in client.last_error


# ---------- подключение к run_pipeline ----------
@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic_llm")
    gen.generate(out_dir=out, meta_dir=out)
    return out


def test_pipeline_llm_without_key_and_cache_falls_back_to_rules_only(synth, tmp_path):
    s = run_pipeline(synth, tmp_path / "a.db", "llm")                  # conftest: нет ключа, кэш пуст
    assert s["mode"] == "rules_only" and s["requested_mode"] == "llm" and "недоступен" in s["banner"]
    assert s["ai"]["calls"] == 0


def test_pipeline_llm_uses_gemini_judge_with_fake_client(synth, tmp_path):
    client = LlmClient(LLM, transport=FakeTransport(GOOD), cache=LlmCache(tmp_path / "cache"), sleep=lambda s: None, env={})
    s = run_pipeline(synth, tmp_path / "b.db", "llm", judge=GeminiPairJudge(client, CFG))
    assert s["mode"] == "llm" and s["banner"] is None
    assert s["ai"]["pairs_asked"] > 0 and s["ai"]["calls"] == client.stats.calls > 0
    assert s["ai"]["calls"] + s["ai"]["cache_hits"] + s["ai"]["no_answer"] >= s["ai"]["pairs_asked"]


def test_pipeline_no_answer_keeps_rows_ambiguous_not_absent(synth, tmp_path):
    base = run_pipeline(synth, tmp_path / "c0.db", "rules_only")
    client = LlmClient(LLM, transport=FakeTransport(ConnectionError("down")), cache=LlmCache(tmp_path / "cache"),
                       sleep=lambda s: None, env={})
    s = run_pipeline(synth, tmp_path / "c.db", "llm", judge=GeminiPairJudge(client, CFG))
    assert s["mode"] == "llm" and s["ai"]["no_answer"] > 0 and s["ai"]["errors"] > 0
    assert (s["k"], s["a"], s["z"]) == (base["k"], base["a"], base["z"])   # сбой ИИ не меняет результат без ИИ


def test_build_default_ai_returns_judge_that_reports_availability(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "empty"))
    judge_, matcher = build_default_ai(CFG)
    assert judge_.available is False and matcher is None
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    assert build_default_ai(CFG)[0].available is True
