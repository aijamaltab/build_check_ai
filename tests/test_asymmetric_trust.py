"""Асимметричное доверие к отрицательным ответам ИИ: у строки были кандидаты правил -> «в ВОР нет» не даёт уверенного расхождения."""
import copy
import sqlite3
from pathlib import Path

import pytest

from src.config import load_config
from src.pipeline import run_pipeline

SYNTH = Path(__file__).resolve().parents[1] / "data" / "synthetic"
NOTE = "ИИ не подтвердил совпадение, нужна проверка."


class NegativeJudge:
    """Судья пар, который всегда говорит «разные работы»."""
    available = True

    def judge_pair(self, a, b, context=None):
        return {"same_work": False, "confidence": 0.9, "reason": "разные работы"}


class NoneRowMatcher:
    """RowMatcher, который всегда уверенно говорит «в ВОР такой позиции нет»."""
    available = True

    def match_row(self, row, vor_keys):
        return {"key": None, "confidence": 0.95, "reason": "в ВОР нет"}


def run(tmp_path, cfg, mode="llm"):
    db = tmp_path / f"{mode}.db"
    kwargs = {"judge": NegativeJudge(), "row_matcher": NoneRowMatcher()} if mode == "llm" else {}
    run_pipeline(SYNTH, db, mode, cfg=cfg, **kwargs)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = []
    for i in conn.execute("SELECT * FROM issues_view WHERE issue_type = 'missing_in_vor'"):
        had = conn.execute("SELECT 1 FROM staging_match_candidates c JOIN staging_match_rows r ON r.group_id = c.group_id "
                           "JOIN items it ON it.item_id = r.item_id WHERE it.source_file = ? AND it.source_row = ?",
                           (i["source_file"], i["source_row"])).fetchone() is not None
        rows.append({"confidence": i["confidence"], "severity": i["severity"], "text": i["explanation"], "had_candidates": had,
                     "row": (i["source_file"], i["source_row"])})
    conn.close()
    return rows


@pytest.fixture()
def cfg():
    return copy.deepcopy(load_config())


def test_negative_ai_answer_with_rule_candidates_stays_low_confidence(tmp_path, cfg):
    rows = run(tmp_path, cfg)
    with_candidates = [r for r in rows if r["had_candidates"]]
    without = [r for r in rows if not r["had_candidates"]]
    assert with_candidates and without                                   # в демо есть и те, и другие
    assert all(r["confidence"] == "low" and r["severity"] == "low" and NOTE in r["text"] for r in with_candidates)
    assert all("ИИ не нашёл пару среди всех позиций ВОР." in r["text"] for r in without)


def test_rows_without_candidates_keep_the_old_confirmed_behaviour(tmp_path, cfg):
    rows = run(tmp_path, cfg)
    without = [r for r in rows if not r["had_candidates"]]
    assert {r["row"] for r in without} >= {("act_2.xlsx", 35), ("act_3.xlsx", 33)}       # отмостка и видеонаблюдение: кандидатов у правил нет
    assert all(r["confidence"] == "high" and r["severity"] == "high" for r in without)


def test_rule_can_be_switched_off_in_config(tmp_path, cfg):
    cfg["rules"]["issues"]["missing_in_vor"]["candidates_rule"]["enabled"] = False
    rows = run(tmp_path, cfg)
    assert all(r["confidence"] == "high" for r in rows) and not any(NOTE in r["text"] for r in rows)         # прежнее поведение


def test_candidate_score_threshold_comes_from_config(tmp_path, cfg):
    cfg["rules"]["issues"]["missing_in_vor"]["candidates_rule"]["min_candidate_score"] = 101      # ни один кандидат не проходит
    assert all(r["confidence"] == "high" for r in run(tmp_path, cfg))


def test_note_text_and_severity_come_from_config(tmp_path, cfg):
    block = cfg["rules"]["issues"]["missing_in_vor"]["candidates_rule"]
    block.update(note="Своя пометка.", severity="medium")
    rows = [r for r in run(tmp_path, cfg) if r["had_candidates"]]
    assert rows and all("Своя пометка." in r["text"] and r["severity"] == "medium" and r["confidence"] == "low" for r in rows)


def test_rules_only_mode_is_unchanged(tmp_path, cfg):
    rows = run(tmp_path, cfg, "rules_only")
    assert rows and all(r["confidence"] == "low" and NOTE not in r["text"] and "Без ИИ, низкая уверенность" in r["text"] for r in rows)


def test_config_documents_the_rule():
    block = load_config()["rules"]["issues"]["missing_in_vor"]["candidates_rule"]
    assert block["enabled"] is True and block["min_candidate_score"] == load_config()["rules"]["matching"]["llm_lower_bound"]
    assert block["note"] == NOTE and block["severity"] == "low"
