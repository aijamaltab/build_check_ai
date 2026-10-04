"""ui/data.py без Streamlit: временная база из data/synthetic через run_pipeline (режим llm из реального кэша, только чтение, без ключа)."""
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline import run_pipeline
from tests.cache_guard import REAL_CACHE
from ui.data import (AI_NOT_FOUND_NOTE, LOW_CONFIDENCE_NOTE, connect_readonly, fmt_num, impact_split, issues_table, load_results)

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "synthetic"


@pytest.fixture()
def llm_env(monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))        # реальный кэш, только чтение
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def llm_db(llm_env, tmp_path):
    db = tmp_path / "llm.db"
    run_pipeline(DEMO, db, "llm")
    return db


@pytest.fixture()
def rules_db(tmp_path):
    db = tmp_path / "rules.db"
    run_pipeline(DEMO, db, "rules_only")
    return db


def test_load_results_llm_summary_issues_positions_documents(llm_db):
    r = load_results(llm_db)
    s = r["summary"]
    assert (s["mode"], s["requested_mode"], s["banner"], s["caveat"]) == ("llm", "llm", None, None)
    assert (s["n"], s["m"], s["k"], s["a"], s["l"], s["z"], s["files"]) == (180, 0, 3, 0, 0, 13, 9)
    assert s["impact_som"] == 1378030.0 and s["statuses"] == {"red": 11, "yellow": 7, "green": 30}
    assert s["ai"]["calls"] == 0 and s["ai"]["cache_hits"] > 0
    assert len(r["issues"]) == 13 and set(r["issues"]["confidence"]) == {"high"}
    assert {"issue_id", "issue_type", "source_file", "source_sheet", "source_row", "impact_som", "explanation"} <= set(r["issues"].columns)
    assert len(r["positions"].columns) == 10 and r["positions"]["status"].value_counts().to_dict() == s["statuses"]
    docs = r["documents"]
    assert len(docs) == 9 and set(docs["status"]) == {"parsed"} and (docs["failed_checks"] == 0).all()
    assert set(docs["doc_type"]) == {"vor", "estimate", "contract", "act"}


def test_issues_are_sorted_by_impact_with_empty_last(llm_db):
    impact = load_results(llm_db)["issues"]["impact_som"]
    filled = impact.dropna()
    assert list(filled) == sorted(filled, reverse=True) and impact.iloc[len(filled):].isna().all()


def test_database_is_opened_read_only(llm_db):
    conn = connect_readonly(llm_db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a)")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM runs")
    conn.close()


def test_unknown_project_gives_empty_results(llm_db):
    r = load_results(llm_db, project_id="no-such")
    assert r["summary"] == {} and r["issues"].empty and r["positions"].empty and r["documents"].empty


def test_fmt_num():
    assert fmt_num(1378030.0) == "1 378 030" and fmt_num(11.4) == "11,4" and fmt_num(1.9000000000000004) == "1,9"
    assert fmt_num(0) == "0" and fmt_num(None) == "—" and fmt_num(float("nan")) == "—"


def test_impact_split_on_real_and_fake_data(llm_db, rules_db):
    llm = impact_split(load_results(llm_db)["issues"])
    assert llm == {"high": 1378030.0, "low": 0.0, "n_low": 0}
    rules = impact_split(load_results(rules_db)["issues"])
    assert rules == {"high": 366600.0, "low": 1086110.0, "n_low": 12}
    fake = pd.DataFrame({"impact_som": [100.0, None, 50.0], "confidence": ["high", "high", "low"]})
    assert impact_split(fake) == {"high": 100.0, "low": 50.0, "n_low": 1}
    assert impact_split(pd.DataFrame(columns=["impact_som", "confidence"])) == {"high": 0.0, "low": 0.0, "n_low": 0}


def test_issues_table_rows_names_sources_and_rules(llm_db):
    r = load_results(llm_db)
    t = issues_table(r["issues"], r["positions"])
    assert len(t) == 13 and list(t.columns) == ["Тип", "Важность", "Работа", "План", "Факт", "Влияние на бюджет", "Источник", "Пометка",
                                                 "Пояснение"]
    assert t["Источник"].str.contains(r" · лист «.+» · строка \d+", regex=True).all()
    assert t["Пояснение"].str.contains("Требует проверки").all()
    volume = t[(t["Тип"] == "Превышение объёма") & (t["Работа"] == "Арматура А500 d12")].iloc[0]
    assert (volume["План"], volume["Факт"], volume["Влияние на бюджет"]) == ("9,5 т", "11,4 т", "117 800 сом")
    assert volume["Источник"] == "act_2.xlsx · лист «Акт» · строка 12"
    late = t[t["Тип"] == "Акт после срока"]
    assert len(late) == 2 and (late["Влияние на бюджет"].str.startswith("—")).all()
    assert late["План"].str.startswith("срок договора 20").all() and late["Факт"].str.startswith("акт 20").all()
    assert "позже срока договора на 17 дн." in late.iloc[0]["Работа"] + late.iloc[1]["Работа"]
    missing = t[t["Тип"] == "Нет в ВОР"]
    assert len(missing) == 3 and (missing["Пометка"] == AI_NOT_FOUND_NOTE).all() and (missing["План"] == "нет в ВОР").all()
    assert (t[t["Тип"] == "Рост цены"]["План"].str.contains("сом/")).all()


def test_issues_table_low_confidence_and_empty_impact_in_rules_only(rules_db):
    r = load_results(rules_db)
    t = issues_table(r["issues"], r["positions"])
    assert len(t) == 18
    low = t[t["Пометка"] == LOW_CONFIDENCE_NOTE]
    assert len(low) == 12 and (low["Тип"] == "Нет в ВОР").all() and (low["Важность"] == "низкая").all()


def test_issues_table_empty_impact_shows_reason_from_note():
    issues = pd.DataFrame([{"issue_type": "price_increase", "work_key": "work:x|m2", "expected": None, "actual": 120.0, "severity": "high",
                            "source_file": "a.xlsx", "source_sheet": "Акт", "source_row": 5, "explanation": "Возможное расхождение. Требует проверки.",
                            "impact_som": None, "impact_note": "нет цены в смете", "confidence": "high", "unit": "м2",
                            "expected_text": None, "actual_text": None}])
    positions = pd.DataFrame([{"work_key": "work:x|m2", "name": "Штукатурка"}])
    t = issues_table(issues, positions)
    assert t.iloc[0]["Работа"] == "Штукатурка" and t.iloc[0]["Влияние на бюджет"] == "— (нет цены в смете)"
    assert t.iloc[0]["Источник"] == "a.xlsx · лист «Акт» · строка 5"
