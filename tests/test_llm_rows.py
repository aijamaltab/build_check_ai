"""GeminiRowMatcher: пачки, кэш по строке, проверка ответа кодом, подключение к resolve_rows и run_pipeline. Фейковый transport, без сети."""
import json
import re

import pytest

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.llm import GeminiPairJudge, GeminiRowMatcher, LlmClient, build_default_ai
from src.llm.cache import LlmCache
from src.llm.prompts import GRADE_REFERENCE, PAIR_PROMPT_VERSION, ROW_PROMPT_VERSION, UNKNOWN_KIND_RULE
from src.llm.row_matcher import key_ids
from src.matching import compute_matching, load_rows, resolve_rows, save_matching
from src.pipeline import run_pipeline
from tests.project_factory import make_project
from tests.test_generate_synthetic import gen
from tests.test_llm import GOOD, SECRET, RateLimit

CFG = load_config()
LLM = CFG["rules"]["llm"]


def vor_item(name, unit, kind="work"):
    return {"key": f"{kind}:{name.lower()}|{unit}", "name_raw": name, "name": name.lower(), "unit": unit, "kind": kind}


VOR = [vor_item("Кладка стен из кирпича", "m3"), vor_item("Штукатурка стен внутренняя", "m2"),
       vor_item("Штукатурка фасада наружная", "m2"), vor_item("Арматура А500 d12", "t"), vor_item("Арматура А500 d8", "t"),
       vor_item("Монтаж перегородок", "m2")]
IDS = key_ids(VOR)


def key_of(name):
    return next(v["key"] for v in VOR if v["name_raw"] == name)


def row(name, unit, kind=None, **extra):
    return {"name_raw": name, "name": name.lower(), "unit": unit, "kind": kind, **extra}


def item(row_id, vor_name, conf=0.9, reason="тот же вид работ"):
    return {"row_id": row_id, "key": None if vor_name is None else IDS[key_of(vor_name)], "confidence": conf, "reason": reason}


def reply(*items):
    return json.dumps({"answers": list(items)}, ensure_ascii=False)


class Scripted:
    """Transport: f(prompt) -> текст или исключение; запоминает промты."""

    def __init__(self, f):
        self.f, self.prompts = f, []

    def __call__(self, prompt, schema):
        self.prompts.append(prompt)
        out = self.f(prompt)
        if isinstance(out, Exception):
            raise out
        return out


def make(tmp_path, f, **over):
    llm = {**LLM, "call_pause_seconds": 0, **over}
    transport = Scripted(f)
    sleeps = []
    client = LlmClient(llm, transport=transport, cache=LlmCache(tmp_path / "cache"), sleep=sleeps.append, env={})
    return GeminiRowMatcher(client, {**CFG, "rules": {**CFG["rules"], "llm": llm}}), transport, sleeps


def test_correct_key_is_chosen_cached_and_prompt_has_no_numbers_files_price_or_quantity(tmp_path):
    matcher, transport, _ = make(tmp_path, lambda p: reply(item(1, "Кладка стен из кирпича")))
    r = row("Кладка кирпичная стен", "m3", quantity=123.456, unit_price=987.65, file="act_9.xlsx", row=77, sheet="Акт-секрет")
    out = matcher.match_row(r, VOR)
    assert out["key"] == key_of("Кладка стен из кирпича") and out["confidence"] == 0.9
    prompt = transport.prompts[0]
    for hidden in ("123.456", "987.65", "act_9", "77", "Акт-секрет"):
        assert hidden not in prompt
    assert "K1." in prompt and "R1." in prompt and "Кладка стен из кирпича" in prompt and "вид: неизвестен" in prompt
    assert prompt.count("\nK") == len(VOR)                                  # весь список ВОР
    assert matcher.match_row(r, VOR)["key"] == out["key"]                  # из кэша
    assert len(transport.prompts) == 1 and matcher.client.stats.cache_hits == 1


def test_confident_null_means_absent_confirmed(tmp_path):
    matcher, _, _ = make(tmp_path, lambda p: reply(item(1, None, 0.92, "в ВОР такой позиции нет")))
    out = matcher.match_row(row("Установка видеонаблюдения", "set"), VOR)
    assert out["key"] is None and out["confidence"] == 0.92


def test_low_confidence_null_and_low_confidence_key_are_no_decision(tmp_path):
    matcher, _, _ = make(tmp_path, lambda p: reply(item(1, None, 0.4), item(2, "Монтаж перегородок", 0.5)))
    a, b = matcher.match_rows([row("Что-то неясное", "m2"), row("Перегородки", "m2")], VOR)
    assert a is None and b is None and matcher.client.stats.low_confidence == 2


def test_key_outside_the_list_is_rejected_and_not_cached(tmp_path):
    bad = json.dumps({"answers": [{"row_id": 1, "key": "K999", "confidence": 0.95, "reason": "выдумал"}]})
    matcher, _, _ = make(tmp_path, lambda p: bad)
    assert matcher.match_row(row("Кладка кирпичная", "m3"), VOR) is None
    assert matcher.client.stats.rejected_by_check == 1
    assert list((tmp_path / "cache").glob("[!_]*.json")) == []


@pytest.mark.parametrize("r,chosen,why", [
    (row("Кладка кирпичная", "m2"), "Кладка стен из кирпича", "единицы"),                          # единица
    (row("Арматура А500 d8", "t"), "Арматура А500 d12", "d12"),                                    # числовой токен
    (row("Штукатурка стен наружная", "m2"), "Штукатурка стен внутренняя", "слова группы"),         # exclusive_word_groups
    (row("Перегородки", "m2", kind="material"), "Монтаж перегородок", "вид"),                      # вид известен у обеих сторон
])
def test_answer_violating_code_rules_is_rejected_as_no_decision(tmp_path, r, chosen, why):
    matcher, _, _ = make(tmp_path, lambda p: reply(item(1, chosen, 0.95)))
    out = matcher.match_row(r, VOR)
    assert out["key"] is None and out["confidence"] == 0.0 and out["reason"].startswith("отклонено проверкой")
    assert why in out["reason"] and matcher.client.stats.rejected_by_check == 1


def test_batch_is_split_by_config_size_and_duplicates_asked_once(tmp_path):
    def answer_all(prompt):
        n = len(re.findall(r"^R\d+\.", prompt, re.M))
        return reply(*[item(i, None, 0.9) for i in range(1, n + 1)])

    matcher, transport, _ = make(tmp_path, answer_all, row_batch_size=4)
    rows = [row(f"Позиция {i}", "m2") for i in range(9)] + [row("позиция 0", "m2")]       # последняя повторяет первую
    out = matcher.match_rows(rows, VOR)
    assert [len(re.findall(r"^R\d+\.", p, re.M)) for p in transport.prompts] == [4, 4, 1]
    assert len(out) == 10 and all(o["key"] is None for o in out)


def test_batch_partially_cached_sends_only_new_rows(tmp_path):
    matcher, transport, _ = make(tmp_path, lambda p: reply(item(1, None), item(2, None), item(3, None)))
    matcher.match_rows([row("Строка А", "m2"), row("Строка Б", "m2")], VOR)
    out = matcher.match_rows([row("Строка А", "m2"), row("Строка Б", "m2"), row("Строка В", "m2")], VOR)
    assert len(transport.prompts) == 2
    second = transport.prompts[1]
    assert "Строка В" in second and "Строка А" not in second and "Строка Б" not in second and "R2." not in second
    assert matcher.client.stats.cache_hits == 2 and all(o["key"] is None for o in out)


def test_changed_vor_list_does_not_reuse_row_cache(tmp_path):
    matcher, transport, _ = make(tmp_path, lambda p: reply(item(1, None)))
    matcher.match_row(row("Строка А", "m2"), VOR)
    matcher.match_row(row("Строка А", "m2"), VOR + [vor_item("Новая позиция", "m2")])
    assert len(transport.prompts) == 2


def test_invalid_json_retries_once_then_no_decision(tmp_path):
    matcher, transport, sleeps = make(tmp_path, lambda p: "не json")
    assert matcher.match_rows([row("А", "m2"), row("Б", "m2")], VOR) == [None, None]
    assert len(transport.prompts) == 2 and matcher.client.stats.errors == 2 and matcher.client.stats.no_answer == 2
    assert list((tmp_path / "cache").glob("[!_]*.json")) == []


def test_429_is_retried_and_success_after_retry_is_cached(tmp_path):
    calls = []

    def flaky(prompt):
        calls.append(1)
        return RateLimit("429 RESOURCE_EXHAUSTED") if len(calls) == 1 else reply(item(1, None))

    matcher, transport, sleeps = make(tmp_path, flaky)
    assert matcher.match_row(row("Строка А", "m2"), VOR)["key"] is None
    assert len(transport.prompts) == 2 and sleeps and matcher.client.stats.quota_errors == 1
    assert len(list((tmp_path / "cache").glob("[!_]*.json"))) == 1


def test_api_failure_gives_no_decision_not_exception(tmp_path):
    matcher, _, _ = make(tmp_path, lambda p: ConnectionError("down"))
    assert matcher.match_row(row("Строка А", "m2"), VOR) is None


def test_model_may_skip_a_row_of_the_batch(tmp_path):
    matcher, _, _ = make(tmp_path, lambda p: reply(item(2, None)))                        # про строку 1 ни слова
    first, second = matcher.match_rows([row("Строка А", "m2"), row("Строка Б", "m2")], VOR)
    assert first is None and second["key"] is None and matcher.client.stats.no_answer == 1


def test_secret_never_reaches_cache_or_error_text(tmp_path):
    llm = {**LLM, "call_pause_seconds": 0}
    client = LlmClient(llm, transport=Scripted(lambda p: RuntimeError(f"key={SECRET}")), cache=LlmCache(tmp_path / "cache"),
                       sleep=lambda s: None, env={llm["api_key_env"]: SECRET})
    GeminiRowMatcher(client, CFG).match_row(row("Строка А", "m2"), VOR)
    cache_text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "cache").glob("*"))
    assert SECRET not in client.last_error + cache_text


def test_prompts_carry_grade_reference_and_unknown_kind_rule_and_versions(tmp_path):
    assert ROW_PROMPT_VERSION == "row-v1" and PAIR_PROMPT_VERSION == "pair-v3"
    for needle in ("В22,5 ≈ М300", "В25 ≈ М350", "В30 ≈ М400"):
        assert needle in GRADE_REFERENCE
    assert "не упоминай вид работ" in UNKNOWN_KIND_RULE
    matcher, transport, _ = make(tmp_path, lambda p: reply(item(1, None)))
    matcher.match_row(row("Строка А", "m2"), VOR)
    seen = []
    client = LlmClient({**LLM, "call_pause_seconds": 0}, transport=lambda p, s: seen.append(p) or GOOD, cache=LlmCache(tmp_path / "c2"),
                       sleep=lambda s: None, env={})
    GeminiPairJudge(client, CFG).judge_pair({"name_raw": "А", "name": "а", "unit": "m2", "kind": None},
                                            {"name_raw": "Б", "name": "б", "unit": "m2", "kind": "work"}, {})
    for prompt in (transport.prompts[0], seen[0]):
        assert "В22,5 ≈ М300" in prompt and "не упоминай вид работ" in prompt


# ---------- resolve_rows и run_pipeline ----------
def project_db(tmp_path):
    folder = make_project(tmp_path / "proj", vor=[("Кладка кирпичная стен", "м3", 100)],
                          estimate=[("Кладка кирпичная стен", "м3", 100, 1000)],
                          acts=[[("Возведение ограждающих конструкций", "м3", 10, None), ("Работы по этажам кирпичные", "м3", 5, None)]])
    conn = get_connection(":memory:")
    ingest_dir(conn, folder, "demo", CFG)
    save_matching(conn, compute_matching(load_rows(conn, "demo"), CFG), "demo", CFG)
    return conn


def test_two_rows_of_one_document_cannot_take_one_key_higher_confidence_wins(tmp_path):
    conn = project_db(tmp_path)
    todo = conn.execute("SELECT COUNT(*) FROM staging_match_groups WHERE doc_type = 'act' AND status IN ('ambiguous', 'absent')").fetchone()[0]
    assert todo == 2

    def both_to_k1(prompt):
        n = len(re.findall(r"^R\d+\.", prompt, re.M))
        return json.dumps({"answers": [{"row_id": i, "key": "K1", "confidence": 0.95 - 0.1 * (i - 1), "reason": "кладка"}
                                       for i in range(1, n + 1)]})

    matcher, _, _ = make(tmp_path, both_to_k1)
    stats = resolve_rows(conn, matcher, CFG, "demo")
    assert stats.accepted == 1 and stats.reasons == {"rejected: key taken": 1}
    matched = conn.execute("SELECT COUNT(*) FROM staging_match_groups WHERE doc_type = 'act' AND status = 'matched'").fetchone()[0]
    assert matched == 1
    assert matcher.client.stats.calls == 1                                       # обе строки одним вызовом


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic_rows")
    gen.generate(out_dir=out, meta_dir=out)
    return out


def test_pipeline_confident_null_makes_missing_in_vor_high_confidence(synth, tmp_path):
    def all_null(prompt):
        n = len(re.findall(r"^R\d+\.", prompt, re.M))
        return reply(*[item(i, None, 0.95, "в ВОР нет") for i in range(1, n + 1)])

    matcher, transport, _ = make(tmp_path, all_null)
    s = run_pipeline(synth, tmp_path / "p.db", "llm", row_matcher=matcher, cfg=CFG, auto_ai=False)
    assert s["mode"] == "llm" and s["ai"]["rows_asked"] > 0 and s["ai"]["rows_none"] == s["ai"]["rows_asked"]
    assert s["ai"]["calls"] == len(transport.prompts) >= 2                      # пачки по row_batch_size
    import sqlite3
    conn = sqlite3.connect(tmp_path / "p.db")
    rows = conn.execute("SELECT confidence FROM issues_view WHERE issue_type = 'missing_in_vor'").fetchall()
    assert rows and all(r[0] == "high" for r in rows)


def test_pipeline_without_key_and_cache_still_falls_back(synth, tmp_path):
    judge, matcher = build_default_ai(CFG)
    assert judge.available is False and matcher.available is False
    s = run_pipeline(synth, tmp_path / "f.db", "llm")
    assert s["mode"] == "rules_only" and s["banner"]


def test_pipeline_row_matcher_failure_keeps_rules_only_result(synth, tmp_path):
    base = run_pipeline(synth, tmp_path / "b0.db", "rules_only")
    matcher, _, _ = make(tmp_path, lambda p: ConnectionError("down"))
    s = run_pipeline(synth, tmp_path / "b1.db", "llm", row_matcher=matcher, cfg=CFG, auto_ai=False)
    assert s["mode"] == "llm" and s["ai"]["errors"] > 0 and s["ai"]["rows_accepted"] == 0 and s["ai"]["rows_none"] == 0
    assert (s["k"], s["a"], s["z"]) == (base["k"], base["a"], base["z"])
