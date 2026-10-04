"""Данные для экрана: весь SQL приложения только здесь (docs/partner_tasks.md, раздел 2), плюс подготовка таблиц к показу.

load_results() открывает базу только на чтение. Расчётов здесь нет: числа берутся из views position_status, issues_view и run_summary,
которые строит run_pipeline. Функции показа (impact_split, issues_table) работают с датафреймами и не знают про Streamlit.
"""
import json
import sqlite3
from pathlib import Path

import pandas as pd

from src.config import load_config

TYPE_RU = {"volume_exceeded": "Превышение объёма", "price_increase": "Рост цены", "missing_in_vor": "Нет в ВОР",
           "late_act": "Акт после срока"}
SEVERITY_RU = {"low": "низкая", "medium": "средняя", "high": "высокая"}
LOW_CONFIDENCE_NOTE = "Низкая уверенность, требует проверки"
AI_NOT_FOUND_NOTE = "ИИ не нашёл пару в ВОР, требует проверки"
NO_SUMS = "—"


def connect_readonly(db_path) -> sqlite3.Connection:
    """Только чтение: запись в демо-базу через это соединение невозможна."""
    return sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)


def load_results(db_path, project_id: str = "demo") -> dict:
    """-> {"summary": dict, "issues", "positions", "documents": DataFrame}.

    summary: json из run_summary последнего прогона проекта плюс banner; пустой словарь, если прогонов нет.
    documents: файлы проекта и число непройденных проверок качества (диагностические записи «kind не определён» и
    «не сопоставлено, требует проверки» не считаются: это не проблемы файла)."""
    cfg = load_config()
    diagnostic = (cfg["rules"]["matching"]["kind_unknown_dq_check"], cfg["rules"]["matching"]["ambiguous_dq_check"])
    conn = connect_readonly(db_path)
    try:
        row = conn.execute("SELECT summary_json, banner FROM run_summary WHERE project_id = ? ORDER BY run_id DESC LIMIT 1",
                           (project_id,)).fetchone()
        summary = {}
        if row:
            summary = json.loads(row[0])
            summary["banner"] = row[1]
        issues = pd.read_sql_query("SELECT * FROM issues_view WHERE project_id = ?", conn, params=(project_id,))
        positions = pd.read_sql_query("SELECT * FROM position_status WHERE project_id = ?", conn, params=(project_id,))
        marks = ",".join("?" for _ in diagnostic)
        documents = pd.read_sql_query(
            "SELECT d.doc_id, d.doc_type, d.file_name, d.status, "
            f"COUNT(CASE WHEN c.passed = 0 AND c.check_name NOT IN ({marks}) THEN 1 END) AS failed_checks "
            "FROM documents d LEFT JOIN dq_checks c ON c.doc_id = d.doc_id WHERE d.project_id = ? "
            "GROUP BY d.doc_id ORDER BY d.doc_id", conn, params=(*diagnostic, project_id))
    finally:
        conn.close()
    return {"summary": summary, "issues": issues, "positions": positions, "documents": documents}


# ---------- подготовка к показу (без SQL) ----------
def fmt_num(value) -> str:
    """Тысячи через пробел, десятичная запятая, не больше двух знаков; пусто -> «—»."""
    if value is None or pd.isna(value):
        return NO_SUMS
    text = f"{float(value):,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ").replace(".", ",")


def impact_split(issues: pd.DataFrame) -> dict:
    """Сумма влияния на бюджет по высокой и низкой уверенности (пустое влияние считается нулём) и число расхождений низкой уверенности."""
    if issues.empty:
        return {"high": 0.0, "low": 0.0, "n_low": 0}
    amount = issues["impact_som"].fillna(0)
    low = issues["confidence"] == "low"
    return {"high": float(amount[~low].sum()), "low": float(amount[low].sum()), "n_low": int(low.sum())}


def _plan_fact(r) -> tuple:
    unit = r["unit"] or ""
    if r["issue_type"] == "volume_exceeded":
        return f"{fmt_num(r['expected'])} {unit}".strip(), f"{fmt_num(r['actual'])} {unit}".strip()
    if r["issue_type"] == "price_increase":
        return f"{fmt_num(r['expected'])} сом/{unit}", f"{fmt_num(r['actual'])} сом/{unit}"
    if r["issue_type"] == "missing_in_vor":
        return "нет в ВОР", f"{fmt_num(r['actual'])} {unit}".strip()
    return f"срок договора {r['expected_text']}", f"акт {r['actual_text']}"          # late_act


def issues_table(issues: pd.DataFrame, positions: pd.DataFrame) -> pd.DataFrame:
    """Таблица расхождений для показа в порядке issues_view (по влиянию на бюджет, пустое влияние в конце).

    late_act: без «ожидалось/получилось», вместо плана и факта срок и дата акта, влияние «—»; пустое влияние: «—» и причина из impact_note;
    low confidence: пометка «требует проверки»; missing_in_vor высокой уверенности: «ИИ не нашёл пару в ВОР, требует проверки»
    (гипотеза для проверки, не факт)."""
    names = dict(zip(positions["work_key"], positions["name"])) if not positions.empty else {}
    rows = []
    for _, r in issues.iterrows():
        if r["issue_type"] == "late_act":
            work = f"Акт {r['source_file']} позже срока договора на {fmt_num(r['actual'])} дн."
        else:
            work = names.get(r["work_key"]) or (r["work_key"] or NO_SUMS)
        plan, fact = _plan_fact(r)
        if pd.isna(r["impact_som"]):
            impact = f"{NO_SUMS} ({r['impact_note']})" if r["impact_note"] else NO_SUMS
        else:
            impact = f"{fmt_num(r['impact_som'])} сом"
        if r["confidence"] == "low":
            note = LOW_CONFIDENCE_NOTE
        elif r["issue_type"] == "missing_in_vor":
            note = AI_NOT_FOUND_NOTE
        else:
            note = ""
        rows.append({"Тип": TYPE_RU.get(r["issue_type"], r["issue_type"]), "Важность": SEVERITY_RU.get(r["severity"], r["severity"]),
                     "Работа": work, "План": plan, "Факт": fact, "Влияние на бюджет": impact,
                     "Источник": f"{r['source_file']} · лист «{r['source_sheet']}» · строка {int(r['source_row'])}",
                     "Пометка": note, "Пояснение": r["explanation"]})
    return pd.DataFrame(rows, columns=["Тип", "Важность", "Работа", "План", "Факт", "Влияние на бюджет", "Источник", "Пометка", "Пояснение"])
