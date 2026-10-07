"""Живой ИИ на странице загрузки: ключ, режим клиента, лимиты (сессия, сутки, время), прогресс, утечки ключа. Без сети: фейковый транспорт."""
import os
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config import load_config
from src.llm import LlmClient, build_default_ai
from src.llm.budget import CallBudget, make_gate
from src.llm.cache import LlmCache
from src.llm.prompts import ROW_SCHEMA
from src.pipeline import run_pipeline
from tests.cache_guard import REAL_CACHE
from ui import live_ai
from ui.live_ai import build_live_ai, describe_ai, get_api_key, scrub

ROOT = Path(__file__).resolve().parents[1]
SET_2 = ROOT / "data" / "synthetic_sets" / "set_2"
KEY = "AIzaSy-fake-key-for-tests-0123456789"
LLM = load_config()["rules"]["llm"]
NO_SLEEP = {"sleep": lambda s: None}


class FakeTransport:
    """Вместо Gemini: на пару отвечает «разные работы», на пачку строк «в ВОР такой позиции нет». Сеть не нужна."""
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, prompt, schema):
        FakeTransport.calls += 1
        if schema is ROW_SCHEMA:
            return '{"answers": [' + ",".join(f'{{"row_id": {i}, "key": null, "confidence": 0.95, "reason": "нет в ВОР"}}' for i in range(1, 11)) + "]}"
        return '{"same_work": false, "confidence": 0.9, "reason": "разные работы"}'


def valid(answer):
    return isinstance(answer, dict)


@pytest.fixture()
def live_env(monkeypatch, tmp_path):
    """Живой режим на временном кэше (реальный кэш не трогаем), без пауз по rpm, с фейковым транспортом."""
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")                         # как на сайте: глобальный режим «только кэш»
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr("src.llm.client.GenaiTransport", FakeTransport)
    monkeypatch.setattr(live_ai, "EXTRA_OVERRIDES", {"call_pause_seconds": 0})
    FakeTransport.calls = 0


# ---------- ключ и режим клиента ----------
def test_api_key_from_secrets_then_environment():
    assert get_api_key({"GEMINI_API_KEY": "  from-secrets "}, env={"GEMINI_API_KEY": "from-env"}) == "from-secrets"
    assert get_api_key({}, env={"GEMINI_API_KEY": "from-env"}) == "from-env"
    assert get_api_key(None, env={}) is None

    class Broken:
        def get(self, name):
            raise FileNotFoundError("secrets.toml")
    assert get_api_key(Broken(), env={}) is None                       # нет файла secrets: это «ключа нет», а не падение


def test_scrub_removes_key_from_text():
    assert KEY not in scrub(f"401 bad key {KEY} for request", KEY) and "***" in scrub(f"key={KEY}", KEY)
    assert scrub("без ключа", None) == "без ключа"


def test_client_mode_is_explicit_and_independent_of_environment(tmp_path):
    env = {"LLM_CACHE_ONLY": "1", "GEMINI_API_KEY": "from-env"}
    cache = LlmCache(tmp_path)
    assert LlmClient(LLM, env=env, cache=cache).cache_only is True                           # по умолчанию как раньше: окружение решает
    live = LlmClient(LLM, env=env, cache=cache, cache_only=False, api_key=KEY, transport=FakeTransport())
    assert live.cache_only is False and live.can_call_api and live.has_key
    offline = LlmClient(LLM, env={}, cache=cache, cache_only=True, api_key=KEY, transport=FakeTransport())
    assert offline.can_call_api is False and offline.generate("p", {}, valid) is None         # «только кэш» сильнее ключа
    assert env == {"LLM_CACHE_ONLY": "1", "GEMINI_API_KEY": "from-env"}                      # окружение не менялось


def test_build_live_ai_with_and_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    cfg = load_config()
    judge, rows, live = build_live_ai(cfg, KEY, CallBudget(5), CallBudget(5))
    assert live and judge.client.can_call_api and judge.client is rows.client and os.environ["LLM_CACHE_ONLY"] == "1"
    judge, rows, live = build_live_ai(cfg, None, CallBudget(5), CallBudget(5))
    assert not live and not judge.client.can_call_api                                           # без ключа страница работает на кэше


# ---------- лимиты ----------
def test_gate_stops_after_session_limit_and_run_stops_cleanly(tmp_path):
    session, site = CallBudget(2), CallBudget(100, daily=True)
    client = LlmClient(LLM, env={}, cache=LlmCache(tmp_path), cache_only=False, api_key=KEY, transport=FakeTransport(),
                       gate=make_gate(session, site), **NO_SLEEP)
    results = [client.generate("p", {}, valid) for _ in range(4)]
    assert results[:2] == [{"same_work": False, "confidence": 0.9, "reason": "разные работы"}] * 2 and results[2:] == [None, None]
    assert client.stats.calls == 2 and "сессии (2)" in client.stop_reason and site.used == 2


def test_site_daily_limit_and_rollover():
    day = ["2026-10-06"]
    site, session = CallBudget(3, daily=True, today=lambda: day[0]), CallBudget(50)
    gate = make_gate(session, site)
    assert [gate() for _ in range(3)] == [None, None, None]
    assert "суточный лимит" in gate() and site.used == 3 and session.used == 3
    day[0] = "2026-10-07"
    assert gate() is None and site.used == 1                                                   # новые сутки: счётчик сначала
    site.attach_usage(lambda: 3)                                                               # _usage.json клиента показывает больше: берётся оно
    assert site.remaining == 0


def test_time_limit_stops_the_run(tmp_path):
    now = [0.0]

    def transport(prompt, schema):
        now[0] += 50
        return '{"ok": 1}'
    client = LlmClient({**LLM, "max_run_seconds": 90}, env={}, cache=LlmCache(tmp_path), cache_only=False, api_key=KEY,
                       transport=transport, clock=lambda: now[0], **NO_SLEEP)
    answers = [client.generate("p", {}, valid) for _ in range(4)]
    assert answers[:2] == [{"ok": 1}, {"ok": 1}] and answers[2:] == [None, None]
    assert client.stats.calls == 2 and "лимит времени" in client.stop_reason and "90" in client.stop_reason


def test_key_never_reaches_error_texts(tmp_path):
    def transport(prompt, schema):
        raise RuntimeError(f"401 invalid key {KEY} in request")
    client = LlmClient(LLM, env={}, cache=LlmCache(tmp_path), cache_only=False, api_key=KEY, transport=transport, **NO_SLEEP)
    assert client.generate("p", {}, valid) is None
    assert client.last_error and KEY not in client.last_error and "***" in client.last_error
    gate_client = LlmClient(LLM, env={}, cache=LlmCache(tmp_path), cache_only=False, api_key=KEY, transport=FakeTransport(),
                            gate=lambda: f"причина с ключом {KEY}", **NO_SLEEP)
    gate_client.generate("p", {}, valid)
    assert KEY not in gate_client.stop_reason
    assert not list(tmp_path.glob("*.json")) or all(KEY not in f.read_text(encoding="utf-8") for f in tmp_path.glob("*.json"))


def test_existing_default_behaviour_without_gate_or_key_is_unchanged(tmp_path):
    client = LlmClient(LLM, env={}, cache=LlmCache(tmp_path), transport=FakeTransport(), **NO_SLEEP)
    assert client.cache_only is False and client.gate is None and client.generate("p", {}, valid) is not None


# ---------- полный прогон на наборе с фейковым ИИ ----------
def test_live_run_on_new_set_reports_progress_and_limit_stop(live_env, tmp_path):
    events = []
    session = CallBudget(5)
    judge, rows, live = build_live_ai(load_config(), KEY, session, CallBudget(100, daily=True), lambda *a: events.append(a))
    summary = run_pipeline(SET_2, tmp_path / "set2.db", "llm", judge, rows, project_id="upload")
    ai = summary["ai"]
    assert live and summary["mode"] == "llm" and ai["calls"] == 5 and session.used == 5
    assert "сессии (5)" in ai["stop_reason"] and ai["pairs_no_decision"] > 0                  # остальные пары остались неоднозначными
    stages = [e[0] for e in events]
    assert stages[0] == "pairs" and events[0][1] == 0 and events[0][2] > 5 and events[-1][1] == events[-1][2]
    done = [e[1] for e in events if e[0] == "pairs"]
    assert done == sorted(done)                                                              # прогресс не откатывается
    text = describe_ai(summary, True)
    assert text["line"].startswith("ИИ: новых запросов 5, из сохранённых ответов") and "Разбор остановлен" in text["stopped"]
    assert "осталось пар" in text["stopped"] and "вручную" in text["stopped"] and KEY not in text["line"] + text["stopped"]
    assert any(list((tmp_path / "cache").glob("*.json")))                                      # ответы пишутся в кэш (временный)


def test_describe_ai_without_key_says_so():
    text = describe_ai({"ai": {"calls": 0, "cache_hits": 12, "pairs_no_decision": 0, "rows_no_decision": 0, "stop_reason": None}}, False)
    assert text["line"].startswith("ИИ: новых запросов 0, из сохранённых ответов 12.") and "Ключ ИИ не настроен" in text["line"]
    assert text["stopped"] is None


# ---------- страница ----------
def upload_app():
    from ui.screens import upload
    upload.render()


def page_text(at) -> str:
    parts = [m.value for m in at.markdown] + [i.value for i in at.info] + [w.value for w in at.warning] + [e.value for e in at.error]
    parts += [str(at.session_state[k]) for k in at.session_state]
    return "\n".join(parts)


def test_page_with_key_shows_privacy_warning_and_limits(live_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    assert not at.exception
    assert any("Загружайте только учебные или обезличенные документы. Названия работ из загруженных файлов отправляются во внешний сервис ИИ"
               in w.value for w in at.warning)
    assert any("разбирает ИИ в реальном времени" in i.value and "25 запросов на сессию" in i.value and "150 в сутки" in i.value for i in at.info)
    assert KEY not in page_text(at)


UPLOAD_KEYS = {"vor": "upload_vor", "act": "upload_acts", "estimate": "upload_estimate", "contract": "upload_contract"}


def upload_folder(at, folder):
    """Кладёт все девять файлов набора в поля загрузки страницы (ВОР, акты, смета, договор)."""
    for path in sorted(folder.glob("*.xlsx")):
        at.file_uploader(key=UPLOAD_KEYS[path.stem.split("_")[0]]).upload(path.name, path.read_bytes())


def test_page_runs_new_files_with_live_ai_and_saves_counts(live_env, monkeypatch):
    from ui.screens import upload
    monkeypatch.setattr(upload, "site_budget", lambda: CallBudget(1000, daily=True))
    at = AppTest.from_function(upload_app, default_timeout=180)
    at.session_state["live_budget"] = CallBudget(1000)
    at.run()
    upload_folder(at, SET_2)
    at.button(key="upload_run").click().run()
    assert not at.exception and not at.error
    run = at.session_state["run_result"]
    ai = describe_ai(run["summary"], run["live"])
    assert FakeTransport.calls > 25 and run["summary"]["ai"]["calls"] == FakeTransport.calls      # лимит сессии 25 здесь поднят, ответы живые
    assert f"ИИ: новых запросов {FakeTransport.calls}" in ai["line"] and ai["stopped"] is None
    assert KEY not in page_text(at)


def test_page_stops_politely_when_session_limit_is_exhausted(live_env, monkeypatch):
    from ui.screens import upload
    monkeypatch.setattr(upload, "site_budget", lambda: CallBudget(1000, daily=True))
    at = AppTest.from_function(upload_app, default_timeout=180)
    at.session_state["live_budget"] = CallBudget(3)
    at.run()
    upload_folder(at, ROOT / "data" / "synthetic_sets" / "set_3")
    at.button(key="upload_run").click().run()
    assert not at.exception and not at.error
    run = at.session_state["run_result"]
    stopped = describe_ai(run["summary"], run["live"])["stopped"]
    assert "Разбор остановлен" in stopped and "лимит живых ИИ-запросов для вашей сессии (3)" in stopped and "осталось пар" in stopped
    assert run["results"]["issues"] is not None and KEY not in page_text(at)                     # результат всё равно собран
    assert FakeTransport.calls == 3


def test_demo_sets_use_cache_only_even_when_the_key_is_set(live_env, monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    at.button(key="run_set_3").click().run()
    assert not at.exception and FakeTransport.calls == 0 and at.session_state["run_result"]["live"] is False


def test_page_without_key_uses_cache_and_never_calls_api(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr("src.llm.client.GenaiTransport", FakeTransport)
    FakeTransport.calls = 0
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    at.button(key="run_base").click().run()
    assert not at.exception and FakeTransport.calls == 0
    run = at.session_state["run_result"]
    assert run["summary"]["ai"]["calls"] == 0 and run["summary"]["ai"]["cache_hits"] > 0
