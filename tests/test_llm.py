"""ИИ-слой: клиент, кэш, повторы, GeminiPairJudge. Только фейковый transport: без сети и без ключа."""
import json
from pathlib import Path

import pytest

from src.config import load_config
from src.llm import GeminiPairJudge, LlmClient, build_default_ai
from src.llm.cache import LlmCache
from src.pipeline import run_pipeline
from tests.test_generate_synthetic import gen

CFG = load_config()
ROOT_DIR = Path(__file__).resolve().parents[1]
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
    assert len(list((tmp_path / "cache").glob("[!_]*.json"))) == 1
    assert j.judge_pair(*pair())["same_work"] is True            # повтор: из кэша, API не вызывается
    assert (client._transport.calls, client.stats.cache_hits) == (1, 1)


def test_cache_record_has_model_prompt_version_time_and_no_secret(tmp_path):
    client, _ = make(tmp_path, GOOD, env={LLM["api_key_env"]: SECRET})
    judge(client).judge_pair(*pair())
    text = next((tmp_path / "cache").glob("[!_]*.json")).read_text(encoding="utf-8")
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
    assert len(sleeps) == 1 and list((tmp_path / "cache").glob("[!_]*.json")) == []   # плохой ответ не кэшируется


def test_bad_then_good_answer_succeeds_on_retry(tmp_path):
    client, _ = make(tmp_path, "не json", GOOD)
    assert judge(client).judge_pair(*pair())["same_work"] is True
    assert (client.stats.calls, client.stats.errors, client.stats.no_answer) == (2, 1, 0)


def test_429_retries_with_exponential_pause_capped_by_config(tmp_path):
    client, sleeps = make(tmp_path, RateLimit("429 RESOURCE_EXHAUSTED"), GOOD,
                          cfg_over={"max_retries": 3, "retry_pause_seconds": 2, "retry_max_pause_seconds": 3, "quota_abort_after": 99})
    assert judge(client).judge_pair(*pair())["same_work"] is True
    client2, sleeps2 = make(tmp_path / "x", RateLimit("429"),
                            cfg_over={"max_retries": 3, "retry_pause_seconds": 2, "retry_max_pause_seconds": 3, "quota_abort_after": 99})
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


# ---------- квоты: 429, retry delay, суточный лимит, остановка прогона ----------
class QuotaError(Exception):
    """Как ошибка SDK: code и details из ответа Google (RetryInfo, QuotaFailure)."""

    def __init__(self, delay=None, quota_id="GenerateRequestsPerMinutePerProjectPerModel-FreeTier"):
        super().__init__("429 RESOURCE_EXHAUSTED. You exceeded your current quota")
        self.code = 429
        info = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": quota_id}]}]
        if delay:
            info.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": f"{delay}s"})
        self.details = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": info}}


def test_quota_errors_and_no_answers_are_never_cached(tmp_path):
    client, _ = make(tmp_path, QuotaError(5), cfg_over={"quota_abort_after": 99})
    assert judge(client).judge_pair(*pair()) is None
    assert client.stats.quota_errors == 2 and client.stats.no_answer == 1
    assert list((tmp_path / "cache").glob("[!_]*")) == []
    # квота вернулась: тот же вопрос теперь получает ответ, а не «нет решения» из кэша
    client._transport = FakeTransport(GOOD)
    assert judge(client).judge_pair(*pair())["same_work"] is True


def test_429_waits_for_retry_delay_from_error_with_cap(tmp_path):
    client, sleeps = make(tmp_path, QuotaError(37), GOOD)
    assert judge(client).judge_pair(*pair())["same_work"] is True
    assert sleeps == [37.0]                                           # а не слепое удвоение retry_pause_seconds
    capped, sleeps = make(tmp_path / "c", QuotaError(500), GOOD, cfg_over={"retry_max_pause_seconds": 60})
    judge(capped).judge_pair(*pair())
    assert sleeps == [60]


def test_retry_delay_is_read_from_message_text_too(tmp_path):
    from src.llm.client import parse_quota_error
    assert parse_quota_error(RuntimeError("429 ... Please retry in 12.5s."))[0] == 12.5
    assert parse_quota_error(RuntimeError("retry_delay { seconds: 8 }"))[0] == 8
    assert parse_quota_error(RuntimeError("429 quota"))[0] is None


def test_daily_quota_stops_run_without_new_calls(tmp_path):
    daily = QuotaError(quota_id="GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    client, sleeps = make(tmp_path, daily)
    j = judge(client)
    assert j.judge_pair(*pair("Бетон М300")) is None
    assert client.stop_reason and "суточная квота исчерпана" in client.stop_reason and "завтра" in client.stop_reason
    calls = client._transport.calls
    assert calls == 1 and sleeps == []                                # без повтора и без ожидания
    assert j.judge_pair(*pair("Бетон М350")) is None
    assert client._transport.calls == calls and j.stop_reason == client.stop_reason


def test_minute_limit_is_not_treated_as_daily(tmp_path):
    client, _ = make(tmp_path, QuotaError(3), GOOD)
    judge(client).judge_pair(*pair())
    assert client.stop_reason is None


def test_run_stops_after_n_consecutive_429_and_keeps_cache_hits(tmp_path):
    seeded, _ = make(tmp_path, GOOD)
    judge(seeded).judge_pair(*pair("Бетон М300"))                      # ответ, полученный до сбоя
    client, _ = make(tmp_path, QuotaError(1), cfg_over={"quota_abort_after": 3, "max_retries": 1})
    j = judge(client)
    assert j.judge_pair(*pair("Бетон М300"))["same_work"] is True      # из кэша, API не нужен
    assert j.judge_pair(*pair("Окна ПВХ")) is None                    # 429, повтор, 429 (2 подряд)
    assert client.stop_reason is None
    assert j.judge_pair(*pair("Двери")) is None                       # третий 429 подряд: стоп
    assert client.stop_reason and "подряд" in client.stop_reason and client.stats.calls == 3
    assert j.judge_pair(*pair("Плитка")) is None and client.stats.calls == 3
    assert j.judge_pair(*pair("Бетон М300"))["same_work"] is True      # кэш по-прежнему читается


def test_success_resets_consecutive_429_counter(tmp_path):
    client, _ = make(tmp_path, QuotaError(1), GOOD, QuotaError(1), GOOD, cfg_over={"quota_abort_after": 2})
    j = judge(client)
    assert j.judge_pair(*pair("Бетон М300")) is not None
    assert j.judge_pair(*pair("Окна ПВХ")) is not None
    assert client.stop_reason is None


def test_max_calls_per_run_stops_new_calls(tmp_path):
    client, _ = make(tmp_path, GOOD, cfg_over={"max_calls_per_run": 2})
    j = judge(client)
    for name in ("Бетон М300", "Бетон М350", "Бетон М400"):
        j.judge_pair(*pair(name))
    assert client._transport.calls == 2 and "потолок вызовов" in client.stop_reason
    assert client.stats.no_answer == 1


def test_pipeline_reports_stop_reason(synth, tmp_path):
    client = LlmClient({**LLM, "quota_abort_after": 3}, transport=FakeTransport(QuotaError(1)),
                       cache=LlmCache(tmp_path / "cache"), sleep=lambda s: None, env={})
    s = run_pipeline(synth, tmp_path / "q.db", "llm", judge=GeminiPairJudge(client, CFG))
    assert s["ai"]["stop_reason"] and s["ai"]["quota_errors"] == 3 and s["ai"]["calls"] == 3
    assert s["ai"]["no_answer"] == s["ai"]["pairs_asked"] > 3


def load_run_llm():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import run_llm
    return run_llm


def test_run_llm_script_flags_incomplete_run_and_applies_options(synth, tmp_path, monkeypatch, capsys):
    run_llm = load_run_llm()
    made = {}

    def fake_build(cfg):
        made["llm"] = cfg["rules"]["llm"]
        client = LlmClient(cfg["rules"]["llm"], transport=FakeTransport(QuotaError(1)), cache=LlmCache(tmp_path / "cache"),
                           sleep=lambda s: None, env={})
        return GeminiPairJudge(client, cfg), None

    monkeypatch.setattr(run_llm, "build_default_ai", fake_build)
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    code = run_llm.main(["--source", str(synth), "--db", str(tmp_path / "r.db"), "--pause", "0", "--max-calls", "50",
                         "--model", "test-model"])
    out = capsys.readouterr().out
    assert code == 2 and "ПРОГОН НЕПОЛНЫЙ, ЦИФРЫ НЕ ИСПОЛЬЗОВАТЬ" in out and "ПРОГОН ОСТАНОВЛЕН" in out
    assert "осталось" in out and "из " in out and SECRET not in out
    assert (made["llm"]["call_pause_seconds"], made["llm"]["max_calls_per_run"], made["llm"]["model"]) == (0, 50, "test-model")


def test_run_llm_script_complete_run_has_no_incomplete_warning(synth, tmp_path, monkeypatch, capsys):
    run_llm = load_run_llm()
    monkeypatch.setattr(run_llm, "build_default_ai", lambda cfg: (GeminiPairJudge(LlmClient(
        cfg["rules"]["llm"], transport=FakeTransport(json.dumps({"same_work": False, "confidence": 0.95, "reason": "нет"})),
        cache=LlmCache(tmp_path / "cache"), sleep=lambda s: None, env={}), cfg), None))
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    code = run_llm.main(["--source", str(synth), "--db", str(tmp_path / "r2.db"), "--pause", "0"])
    out = capsys.readouterr().out
    assert code == 0 and "НЕПОЛНЫЙ" not in out


# ---------- таблица лимитов, пауза по rpm, суточный счётчик ----------
def test_config_has_limits_table_and_default_model():
    assert LLM["model"] == "gemini-3.1-flash-lite" and "preview" not in LLM["model"]
    assert LLM["limits"]["gemini-3.1-flash-lite"] == {"rpm": 15, "rpd": 500}
    assert LLM["limits"]["gemini-2.5-flash"] == {"rpm": 5, "rpd": None}
    assert LLM["limits"]["gemini-2.5-flash-lite"] == {"rpm": 10, "rpd": 20}
    assert LLM["limits"]["gemini-3-flash"] == {"rpm": 5, "rpd": 20}
    text = (ROOT_DIR / "config" / "rules.yaml").read_text(encoding="utf-8")
    assert "04.10.2026" in text and "перепроверять" in text


def test_pause_is_60_over_rpm_with_margin_and_overridable(tmp_path):
    client = LlmClient(LLM, cache=LlmCache(tmp_path / "c"), env={})
    assert client.call_pause == pytest.approx(5.0)                       # 15 rpm: 60/15 * 1.25
    assert LlmClient({**LLM, "model": "gemini-2.5-flash"}, cache=LlmCache(tmp_path / "c"), env={}).call_pause == pytest.approx(15.0)
    assert LlmClient({**LLM, "model": "unknown-model"}, cache=LlmCache(tmp_path / "c"), env={}).call_pause == LLM["fallback_pause_seconds"]
    assert LlmClient({**LLM, "call_pause_seconds": 2}, cache=LlmCache(tmp_path / "c"), env={}).call_pause == 2


def daily_client(tmp_path, rpd, day="2026-10-04", transport=None, **over):
    cfg = {**LLM, "model": "m-limited", "limits": {"m-limited": {"rpm": 60, "rpd": rpd}}, "call_pause_seconds": 0, **over}
    return LlmClient(cfg, transport=transport or FakeTransport(GOOD), cache=LlmCache(tmp_path / "cache"),
                     sleep=lambda s: None, env={}, today=lambda: day)


def test_daily_counter_is_stored_in_service_file_without_secrets_and_not_counted_as_cache(tmp_path):
    client = daily_client(tmp_path, 100)
    j = judge(client)
    j.judge_pair(*pair("Бетон М300"))
    j.judge_pair(*pair("Бетон М350"))
    usage = tmp_path / "cache" / "_usage.json"
    data = json.loads(usage.read_text(encoding="utf-8"))
    assert data == {"date": "2026-10-04", "models": {"m-limited": 2}}
    assert len(list((tmp_path / "cache").glob("[!_]*.json"))) == 2          # служебный файл не запись кэша
    only_usage = LlmCache(tmp_path / "u")
    only_usage.dir.mkdir()
    (only_usage.dir / "_usage.json").write_text("{}", encoding="utf-8")
    assert only_usage.is_empty()


def test_daily_counter_survives_restart_and_resets_next_day(tmp_path):
    judge(daily_client(tmp_path, 100)).judge_pair(*pair())
    assert daily_client(tmp_path, 100).usage.used("m-limited") == 1
    assert daily_client(tmp_path, 100, day="2026-10-05").usage.used("m-limited") == 0


def test_warning_near_rpd_and_stop_at_rpd(tmp_path):
    client = daily_client(tmp_path, 5)
    j = judge(client)
    for i in range(3):
        j.judge_pair(*pair(f"Бетон М{300 + i}"))
    assert client.warnings == []                                           # 3 из 5 = 60%
    j.judge_pair(*pair("Бетон М400"))                                      # перед четвёртым вызовом использовано 3, после 4 (80%)
    j.judge_pair(*pair("Бетон М450"))
    assert client.warnings and "4 из 5" in client.warnings[0]
    assert client.stop_reason is None
    assert j.judge_pair(*pair("Бетон М500")) is None                      # 5 из 5 использовано: стоп без вызова
    assert client._transport.calls == 5 and "суточный лимит" in client.stop_reason and "5 из 5" in client.stop_reason


def test_daily_limit_already_used_up_blocks_calls_but_not_cache(tmp_path):
    seeded = daily_client(tmp_path, 1)
    judge(seeded).judge_pair(*pair())
    again = daily_client(tmp_path, 1)
    assert judge(again).judge_pair(*pair())["same_work"] is True            # из кэша
    assert judge(again).judge_pair(*pair("Окна ПВХ")) is None
    assert again._transport.calls == 0 and again.stop_reason


def test_unknown_rpd_means_no_daily_stop(tmp_path):
    client = daily_client(tmp_path, None)
    for i in range(3):
        judge(client).judge_pair(*pair(f"Бетон М{300 + i}"))
    assert client.stop_reason is None and client.warnings == []
