"""RowMatcher: ИИ выбирает ключ из всего списка ВОР (реального LLM нет, матчеры фейковые), проверка ответа кодом."""
import importlib.util
from pathlib import Path

import pytest

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.matching import (NoopRowMatcher, compute_matching, load_rows, resolve_candidates, resolve_rows, save_matching,
                          vor_key_list)
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()
M = CFG["rules"]["matching"]

spec = importlib.util.spec_from_file_location("verify_matching", ROOT / "scripts" / "verify_matching.py")
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    generated = gen.generate(out_dir=out, meta_dir=out)
    return out, {(r["file"], r["row"]): r["item_no"] for r in generated.log}


@pytest.fixture()
def db(synth):
    conn = get_connection(":memory:")
    ingest_dir(conn, synth[0], "demo", CFG)
    save_matching(conn, compute_matching(load_rows(conn, "demo"), CFG), "demo", CFG)
    return conn


def q(conn, sql, *args):
    return [tuple(r) for r in conn.execute(sql, args)]


class Fixed:
    """Матчер, который на каждую строку отвечает по функции answer(row, vor_keys)."""
    available = True

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def match_row(self, row, vor_keys):
        self.calls.append(row)
        return self.answer(row, vor_keys)


def key_of(vor_keys, name_part):
    return next(k["key"] for k in vor_keys if name_part in k["name"])


# ---------- по умолчанию ничего не меняется ----------
def test_noop_row_matcher_changes_nothing(db):
    before = q(conn := db, "SELECT COUNT(*) FROM matches")
    stats = resolve_rows(conn, NoopRowMatcher(), CFG, "demo")
    n = q(conn, "SELECT COUNT(*) FROM staging_match_groups WHERE doc_type != 'vor' AND status IN ('ambiguous', 'absent')")[0][0]
    assert stats.skipped == n > 0 and stats.asked == stats.accepted == 0
    assert q(conn, "SELECT COUNT(*) FROM matches") == before
    assert NoopRowMatcher().match_row({}, [])["key"] is None


def test_vor_key_list_is_the_whole_vor_of_the_project(db):
    keys = vor_key_list(db, "demo")
    assert len(keys) == 45 and len({k["key"] for k in keys}) == 45
    assert {"key", "name_raw", "name", "unit", "kind", "file", "sheet", "row"} <= set(keys[0])


# ---------- потолок: фейковый матчер по эталону ----------
def test_truth_row_matcher_reaches_the_ceiling(db, synth):
    truth = synth[1]
    stats = resolve_rows(db, vm.TruthRowMatcher(truth), CFG, "demo")
    m = vm.compare_db(db, "demo", truth)
    assert m["rows"] == 130 and m["matched_wrong"] == 0 and m["ambiguous"] == 0 and m["absent_wrong"] == 0
    assert m["matched_ok"] == 128 and m["absent_ok"] == 2                        # отмостка и видеонаблюдение остаются absent
    assert stats.accepted > 0 and stats.rejected == 0 and stats.none == 2
    llm = q(db, "SELECT m.method, e.stage, e.state, e.reason, e.confidence, m.score FROM matches m "
                "JOIN staging_matches_ext e USING(match_id) WHERE m.method = 'llm' AND e.stage = 'llm_row' LIMIT 1")
    assert llm == [("llm", "llm_row", "matched", "эталон генератора", 1.0, None)]
    assert q(db, "SELECT COUNT(*) FROM issues") == [(0,)]


def test_accepted_rows_get_the_vor_key_and_keep_one_to_one(db, synth):
    resolve_rows(db, vm.TruthRowMatcher(synth[1]), CFG, "demo")
    assert q(db, "SELECT COUNT(*) FROM matches m JOIN items a ON a.item_id = m.item_id JOIN items v ON v.item_id = m.matched_to_item_id "
                 "WHERE a.work_key != v.work_key") == [(0,)]
    assert q(db, "SELECT COUNT(*) FROM (SELECT doc_id, matched_group_id FROM staging_match_groups WHERE matched_group_id IS NOT NULL "
                 "GROUP BY doc_id, matched_group_id HAVING COUNT(*) > 1)") == [(0,)]
    assert q(db, "SELECT COUNT(*) FROM (SELECT item_id FROM matches GROUP BY item_id HAVING COUNT(*) > 1)") == [(0,)]
    again = resolve_rows(db, vm.TruthRowMatcher(synth[1]), CFG, "demo")          # повторный запуск: matched не трогаются
    assert again.accepted == 0
    assert q(db, "SELECT COUNT(*) FROM staging_match_groups WHERE status = 'absent'")[0][0] == 2
    assert q(db, "SELECT COUNT(*) FROM dq_checks WHERE check_name = ?", M["ambiguous_dq_check"]) == [(0,)]


def test_pair_judge_then_row_matcher_both_write_llm_matches(db, synth):
    resolve_candidates(db, vm.TruthJudge(synth[1]), CFG, "demo")
    resolve_rows(db, vm.TruthRowMatcher(synth[1]), CFG, "demo")
    stages = {s for (s,) in q(db, "SELECT DISTINCT stage FROM staging_matches_ext WHERE state = 'matched'")}
    assert {"exact", "synonyms", "fuzzy", "llm", "llm_row"} <= stages


# ---------- проверка ответа кодом ----------
def one_row_matcher(answer_key, confidence=1.0, only="арматура гладкая d8"):
    """Матчер, который отвечает только по одной строке (остальным «ни один» с низкой уверенностью)."""
    def answer(row, vor_keys):
        if row["name"] == only:
            return {"key": answer_key(vor_keys) if callable(answer_key) else answer_key, "confidence": confidence, "reason": "тест"}
        return {"key": None, "confidence": 0.0, "reason": "не знаю"}
    return Fixed(answer)


@pytest.mark.parametrize("key,confidence,outcome", [
    ("work:такого ключа нет|m3", 1.0, "rejected: key not in VOR"),
    (lambda keys: key_of(keys, "арматура а240 d8"), 0.1, "rejected: low confidence"),
    (lambda keys: key_of(keys, "кладка"), 1.0, "rejected: unit"),                  # арматура в тоннах, кладка в м3
    (lambda keys: key_of(keys, "арматура а500 d12"), 1.0, "rejected: numeric tokens"),  # d8 против d12 ИИ обойти не может
])
def test_code_rejects_bad_answers(db, key, confidence, outcome):
    stats = resolve_rows(db, one_row_matcher(key, confidence), CFG, "demo")
    assert stats.accepted == 0 and stats.reasons.get(outcome, 0) >= 1, stats.reasons
    assert q(db, "SELECT COUNT(*) FROM matches WHERE method = 'llm'") == [(0,)]
    assert q(db, "SELECT outcome FROM staging_llm_row_decisions WHERE outcome = ? LIMIT 1", outcome) == [(outcome,)]


def test_code_rejects_kind_mismatch(db):
    """Строка с признаком материала не может занять работу ВОР. В данных все материалы уже сопоставлены правилами,
    поэтому у одной неразрешённой группы признак материала выставляется вручную (подготовка теста)."""
    group = db.execute("SELECT group_id, name, unit_norm FROM staging_match_groups WHERE doc_type != 'vor' "
                       "AND status = 'ambiguous' AND unit_norm = 'pcs' LIMIT 1").fetchone()
    db.execute("UPDATE staging_match_groups SET signal = 'material' WHERE group_id = ?", (group["group_id"],))

    def answer(row, keys):
        if row["name"] == group["name"]:
            work = next(k for k in keys if k["kind"] == "work" and k["unit"] == "pcs")
            return {"key": work["key"], "confidence": 1.0, "reason": "тест"}
        return {"key": None, "confidence": 0.0, "reason": "не знаю"}

    stats = resolve_rows(db, Fixed(answer), CFG, "demo")
    assert stats.accepted == 0 and stats.reasons == {"rejected: kind": 1}


def test_vor_key_cannot_be_taken_by_two_groups_of_one_document(db):
    """Две разные группы одного акта (№2) не могут занять один ключ ВОР."""
    def answer(row, keys):
        if row["file"] == "act_2.xlsx" and row["name"] in ("копка грунта вручную", "подготовка из песка"):
            return {"key": next(k["key"] for k in keys if "грунта вручную" in k["name"]), "confidence": 1.0, "reason": "тест"}
        return {"key": None, "confidence": 0.0, "reason": "не знаю"}

    stats = resolve_rows(db, Fixed(answer), CFG, "demo")
    assert stats.accepted == 1 and stats.reasons == {"rejected: key taken": 1}


def test_invalid_answers_and_confident_none(db):
    stats = resolve_rows(db, Fixed(lambda row, keys: {"key": 5, "confidence": "высокая"}), CFG, "demo")
    assert stats.accepted == 0 and stats.reasons["rejected: invalid"] == stats.asked
    # уверенное «ни один» переводит ambiguous в absent, неуверенное оставляет как есть
    n_amb = q(db, "SELECT COUNT(*) FROM staging_match_groups WHERE status = 'ambiguous'")[0][0]
    resolve_rows(db, Fixed(lambda row, keys: {"key": None, "confidence": 0.2, "reason": "не уверен"}), CFG, "demo")
    assert q(db, "SELECT COUNT(*) FROM staging_match_groups WHERE status = 'ambiguous'")[0][0] == n_amb
    resolve_rows(db, Fixed(lambda row, keys: {"key": None, "confidence": 0.99, "reason": "в ВОР такой работы нет"}), CFG, "demo")
    assert q(db, "SELECT COUNT(*) FROM staging_match_groups WHERE status = 'ambiguous'")[0][0] == 0
    assert q(db, "SELECT COUNT(*) FROM staging_match_candidates WHERE status = 'open' AND group_id IN "
                 "(SELECT group_id FROM staging_match_groups WHERE status = 'absent')") == [(0,)]


def test_rerun_of_matching_clears_row_decisions(db, synth):
    resolve_rows(db, vm.TruthRowMatcher(synth[1]), CFG, "demo")
    assert q(db, "SELECT COUNT(*) FROM staging_llm_row_decisions")[0][0] > 0
    save_matching(db, compute_matching(load_rows(db, "demo"), CFG), "demo", CFG)
    assert q(db, "SELECT COUNT(*) FROM staging_llm_row_decisions") == [(0,)]
    assert q(db, "SELECT COUNT(*) FROM matches WHERE method = 'llm'") == [(0,)]
