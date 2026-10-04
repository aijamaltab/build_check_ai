"""Четыре проверки расхождений на маленьких проектах из настоящих xlsx (допуски на границе, накопительность, валюты)."""
import datetime as dt

import pytest

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.matching import compute_matching, load_rows, save_matching
from src.rules import run_checks
from tests.project_factory import make_project

CFG = load_config()
TOL_V = CFG["rules"]["volume_exceeded"]["tolerance_pct"]        # 5
TOL_P = CFG["rules"]["price_increase"]["tolerance_pct"]         # 3

WORK = "Кладка кирпичных стен"


def run(tmp_path, vor, estimate, acts, mode="rules_only", **kw):
    make_project(tmp_path / "p", vor, estimate, acts, **kw)
    conn = get_connection(":memory:")
    ingest_dir(conn, tmp_path / "p", "demo", CFG)
    save_matching(conn, compute_matching(load_rows(conn, "demo"), CFG), "demo", CFG, mode)
    result = run_checks(conn, CFG, "demo", mode)
    return conn, result


def issues(conn, issue_type=None):
    sql = ("SELECT i.*, e.source_sheet, e.impact_som, e.impact_note, e.confidence FROM issues i JOIN staging_issues_ext e USING(issue_id)"
           + (" WHERE i.issue_type = ?" if issue_type else "") + " ORDER BY i.issue_id")
    return conn.execute(sql, (issue_type,) if issue_type else ()).fetchall()


# ---------- объём ----------
@pytest.mark.parametrize("fact,expected_issue", [(103, False), (105, False), (105.5, True), (111, True), (100, False)])
def test_volume_tolerance_boundaries(tmp_path, fact, expected_issue):
    """+3% и ровно +5% внутри допуска (5%), +5,5% и +11% снаружи."""
    conn, res = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 6000)], [[(WORK, "м3", fact, 6000)]])
    assert (len(issues(conn, "volume_exceeded")) == 1) is expected_issue


def test_volume_is_cumulative_over_acts_and_source_is_the_crossing_row(tmp_path):
    """Ни в одном акте по отдельности превышения нет; накопительно 60 + 50 = 110 больше 100 на 10%."""
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 6000)],
                  [[(WORK, "м3", 60, 6000)], [(WORK, "м3", 50, 6000)]],
                  act_dates={1: dt.date(2025, 5, 1), 2: dt.date(2025, 6, 1)})
    (issue,) = issues(conn, "volume_exceeded")
    assert (issue["expected"], issue["actual"], issue["delta"]) == (100, 110, 10)
    assert round(issue["delta_pct"], 6) == 10 and issue["source_file"] == "act_2.xlsx" and issue["source_sheet"] == "Акт"
    assert issue["impact_som"] == 10 * 6000                                    # дельта на цену из сметы
    assert issue["severity"] == "medium" and "Возможное расхождение" in issue["explanation"]


def test_volume_high_severity_from_config(tmp_path):
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 10)], [[(WORK, "м3", 125, 10)]])
    assert issues(conn, "volume_exceeded")[0]["severity"] == "high"          # 25% не ниже high_pct = 20


def test_yellow_position_creates_no_issue(tmp_path):
    """Факт 50% плана: работа идёт, это не расхождение."""
    conn, res = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 6000)], [[(WORK, "м3", 50, 6000)]])
    assert [r for r in issues(conn) if r["issue_type"] != "late_act"] == []


def test_volume_without_estimate_price_has_no_impact_and_a_note(tmp_path):
    conn, _ = run(tmp_path, [(WORK, "м3", 100), ("Другая работа", "м2", 5)], [("Другая работа", "м2", 5, 10)],
                  [[(WORK, "м3", 120, None)]])
    (issue,) = issues(conn, "volume_exceeded")
    assert issue["impact_som"] is None and issue["impact_note"] == CFG["rules"]["issues"]["no_estimate_price_note"]


# ---------- цена ----------
@pytest.mark.parametrize("price,expected_issue", [(1020, False), (1030, False), (1031, True), (1110, True)])
def test_price_tolerance_boundaries(tmp_path, price, expected_issue):
    """+2% и ровно +3% внутри допуска (3%), +3,1% и +11% снаружи."""
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 1000)], [[(WORK, "м3", 10, price)]])
    assert (len(issues(conn, "price_increase")) == 1) is expected_issue


def test_price_is_weighted_by_key_within_one_act(tmp_path):
    """Две строки одного ключа в акте: (10 по 100) и (30 по 140), средневзвешенная 130, смета 100: +30%, влияние 30 × 40."""
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)], [[(WORK, "м3", 10, 100), (WORK, "м3", 30, 140)]])
    (issue,) = issues(conn, "price_increase")
    assert (issue["expected"], round(issue["actual"], 6), round(issue["delta_pct"], 6)) == (100, 130, 30)
    assert issue["impact_som"] == 30 * 40 and issue["severity"] == "high"
    assert "Другие строки позиции" in issue["explanation"]


def test_price_is_checked_per_act_not_across_acts(tmp_path):
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)],
                  [[(WORK, "м3", 10, 100)], [(WORK, "м3", 10, 120)]], act_dates={1: dt.date(2025, 5, 1), 2: dt.date(2025, 6, 1)})
    rows = issues(conn, "price_increase")
    assert len(rows) == 1 and rows[0]["source_file"] == "act_2.xlsx" and rows[0]["delta"] == 20


def test_price_lower_than_estimate_is_not_an_issue(tmp_path):
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)], [[(WORK, "м3", 10, 50)]])
    assert issues(conn, "price_increase") == []


def test_incomparable_currency_skips_price_but_not_volume(tmp_path):
    """Акт в USD (шаблон act_c) против сметы в сомах: цена не сравнивается, пишется dq и счётчик «не сопоставимо»; объём проверяется."""
    conn, res = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)], [[(WORK, "м3", 130, 500)]], usd_acts=(1,))
    assert issues(conn, "price_increase") == []
    assert res.incomparable_rows == 1
    dq = conn.execute("SELECT passed, details FROM dq_checks WHERE check_name = ?", (CFG["rules"]["currency"]["mismatch_dq_check"],)).fetchall()
    assert len(dq) == 1 and dq[0]["passed"] == 0
    assert len(issues(conn, "volume_exceeded")) == 1                            # объём от валюты не зависит


# ---------- позиция только в акте ----------
def test_missing_in_vor_absent_row_rules_only_is_low_confidence(tmp_path):
    conn, res = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)],
                    [[(WORK, "м3", 10, 100), ("Монтаж системы видеонаблюдения", "компл.", 1, 240000)]])
    (issue,) = issues(conn, "missing_in_vor")
    assert (issue["expected"], issue["actual"]) == (0, 1) and issue["impact_som"] == 240000
    assert issue["severity"] == CFG["rules"]["issues"]["missing_in_vor"]["severity_unconfirmed"] != "high"
    assert issue["confidence"] == "low" and "Без ИИ, низкая уверенность, требует проверки" in issue["explanation"]
    assert issue["source_file"] == "act_1.xlsx" and issue["source_row"] >= 1


def test_missing_in_vor_confirmed_by_ai_is_high_confidence(tmp_path):
    from src.matching import resolve_rows

    class NoneMatcher:
        available = True

        def match_row(self, row, vor_keys):
            return {"key": None, "confidence": 0.95, "reason": "в ВОР такой работы нет"}

    make_project(tmp_path / "p", [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)],
                 [[(WORK, "м3", 10, 100), ("Монтаж системы видеонаблюдения", "компл.", 1, 240000)]])
    conn = get_connection(":memory:")
    ingest_dir(conn, tmp_path / "p", "demo", CFG)
    save_matching(conn, compute_matching(load_rows(conn, "demo"), CFG), "demo", CFG, "llm")
    resolve_rows(conn, NoneMatcher(), CFG, "demo")
    run_checks(conn, CFG, "demo", "llm")
    (issue,) = issues(conn, "missing_in_vor")
    assert issue["severity"] == "high" and issue["confidence"] == "high"
    assert "ИИ не нашёл пару" in issue["explanation"] and "Без ИИ" not in issue["explanation"]


def test_ambiguous_row_creates_no_issue(tmp_path):
    """Строка с кандидатами (похожее, но не то же название) это не расхождение: ни missing_in_vor, ни объём."""
    conn, _ = run(tmp_path, [("Утепление фасада плитами", "м2", 100)], [("Утепление фасада плитами", "м2", 100, 100)],
                  [[("Утепл. фасада минватой", "м2", 100, 100)]])
    assert [r for r in issues(conn) if r["issue_type"] != "late_act"] == []
    assert conn.execute("SELECT status FROM staging_match_groups WHERE doc_type = 'act'").fetchone()[0] == "ambiguous"


# ---------- акт после срока ----------
def test_late_act_by_date_with_title_row_as_source(tmp_path):
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)],
                  [[(WORK, "м3", 10, 100)], [(WORK, "м3", 10, 100)]], deadline=dt.date(2025, 9, 30),
                  act_dates={1: dt.date(2025, 9, 30), 2: dt.date(2025, 10, 17)})
    (issue,) = issues(conn, "late_act")                                          # акт в день срока вовремя, второй позже на 17 дней
    assert issue["source_file"] == "act_2.xlsx" and issue["source_row"] == 1 and issue["source_sheet"] == "Акт"
    assert (issue["expected"], issue["actual"], issue["delta"]) == (0, 17, 17)
    assert "2025-10-17" in issue["explanation"] and "2025-09-30" in issue["explanation"] and issue["impact_som"] is None


def test_late_act_does_not_change_when_matching_fails(tmp_path):
    """Просрочка не зависит от сопоставления: строки акта без пары, а late_act всё равно найден."""
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)], [[("Совсем другая работа", "шт", 1, 5)]],
                  act_dates={1: dt.date(2025, 12, 1)})
    assert len(issues(conn, "late_act")) == 1


# ---------- общее ----------
def test_every_issue_has_file_sheet_and_row_and_careful_wording(tmp_path):
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)],
                  [[(WORK, "м3", 130, 150), ("Монтаж системы", "компл.", 1, 10)]], act_dates={1: dt.date(2025, 12, 1)})
    rows = issues(conn)
    assert {r["issue_type"] for r in rows} == {"volume_exceeded", "price_increase", "missing_in_vor", "late_act"}
    for r in rows:
        assert r["source_file"] and r["source_sheet"] and r["source_row"] >= 1
        text = r["explanation"].lower()
        assert "возможное расхождение" in text and "требует проверки" in text
        assert not any(bad in text for bad in ("нарушен", "мошенн", "хищен", "обман"))
    for word in CFG["rules"]["issues"]["explanations"].values():
        assert not any(bad in word.lower() for bad in ("нарушен", "мошенн"))


def test_rerun_of_checks_does_not_duplicate(tmp_path):
    conn, _ = run(tmp_path, [(WORK, "м3", 100)], [(WORK, "м3", 100, 100)], [[(WORK, "м3", 130, 100)]])
    first = len(issues(conn))
    run_checks(conn, CFG, "demo", "rules_only")
    assert len(issues(conn)) == first
    assert conn.execute("SELECT COUNT(*) FROM staging_issues_ext").fetchone()[0] == first
