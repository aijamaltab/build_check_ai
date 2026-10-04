"""Данные для экрана: весь SQL приложения только здесь (docs/partner_tasks.md, раздел 2), плюс подготовка данных к показу.

load_results() открывает базу только на чтение. Расчётов расхождений здесь нет: числа берутся из views position_status, issues_view и
run_summary, которые строит run_pipeline; здесь только форматирование, сборка фраз, сортировка, фильтры и подсчёты для диаграмм.
Всё, что не SQL (fmt_num, build_cards, filter_issues, chart_frames, ...), работает с датафреймами и не знает про Streamlit.
"""
import json
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd

from src.config import load_config

TYPE_ORDER = ["volume_exceeded", "price_increase", "missing_in_vor", "late_act"]
TYPE_RU = {"volume_exceeded": "Превышение объёма", "price_increase": "Рост цены", "missing_in_vor": "Нет в ВОР",
           "late_act": "Акт после срока"}
TYPE_CHART_RU = {**TYPE_RU, "late_act": "Акт после срока договора"}
SEVERITY_ORDER = ["high", "medium", "low"]
SEVERITY_RU = {"high": "высокая", "medium": "средняя", "low": "низкая"}
SEVERITY_COLOR = {"high": "#C62828", "medium": "#F9A825", "low": "#9AA3AE"}
# цвет заливки и цвет текста: контраст не ниже 4.5:1 (проверяется тестом)
STATUS_COLORS = {"red": ("#C62828", "#FFFFFF"), "yellow": ("#F9A825", "#1B1B1B"), "green": ("#2E7D32", "#FFFFFF")}
STATUS_ROW_FILL = {"red": "#FDECEA", "yellow": "#FFF6DB", "green": "#E8F5E9"}       # светлые заливки строк таблицы, текст тёмный
STATUS_PLURAL = {"red": "Красные", "yellow": "Жёлтые", "green": "Зелёные"}
STATUS_SINGULAR = {"red": "Красный", "yellow": "Жёлтый", "green": "Зелёный"}
SOURCE_ROLE = {"vor": "ВОР", "estimate": "Смета", "act": "Акт", "contract": "Договор"}
LOW_CONFIDENCE_NOTE = "Низкая уверенность, требует проверки"
AI_NOT_FOUND_NOTE = "ИИ не нашёл пару в ВОР, требует проверки"
EMPTY = "—"


def connect_readonly(db_path) -> sqlite3.Connection:
    """Только чтение: запись в демо-базу через это соединение невозможна."""
    return sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)


# ---------- чтение из базы (единственное место с SQL) ----------
def load_results(db_path, project_id: str = "demo") -> dict:
    """-> {"summary": dict, "issues", "positions", "documents": DataFrame}.

    summary: json из run_summary последнего прогона проекта плюс banner; пустой словарь, если прогонов нет.
    issues: issues_view плюс колонки sources (строки «роль · файл · лист · строка» по документам, где нашлось расхождение) и
    ai_matched (пара названий склеена моделью). documents: файлы проекта и число непройденных проверок качества (диагностические
    записи «kind не определён» и «не сопоставлено, требует проверки» не считаются)."""
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
        items = pd.read_sql_query("SELECT doc_type, work_key, source_file, source_sheet, source_row FROM items WHERE project_id = ?",
                                  conn, params=(project_id,))
        ai_keys = {r[0] for r in conn.execute(
            "SELECT DISTINCT m.work_key FROM matches m JOIN staging_matches_ext e ON e.match_id = m.match_id "
            "JOIN items i ON i.item_id = m.item_id WHERE i.project_id = ? AND e.stage IN ('llm', 'llm_row')", (project_id,))}
        marks = ",".join("?" for _ in diagnostic)
        documents = pd.read_sql_query(
            "SELECT d.doc_id, d.doc_type, d.file_name, d.status, "
            f"COUNT(CASE WHEN c.passed = 0 AND c.check_name NOT IN ({marks}) THEN 1 END) AS failed_checks "
            "FROM documents d LEFT JOIN dq_checks c ON c.doc_id = d.doc_id WHERE d.project_id = ? "
            "GROUP BY d.doc_id ORDER BY d.doc_id", conn, params=(*diagnostic, project_id))
    finally:
        conn.close()
    return {"summary": summary, "issues": attach_context(issues, items, ai_keys), "positions": positions, "documents": documents}


# ---------- форматирование ----------
def fmt_num(value) -> str:
    """Тысячи через пробел, десятичная запятая, не больше двух знаков; пусто -> «—»."""
    if value is None or pd.isna(value):
        return EMPTY
    text = f"{float(value):,.2f}".rstrip("0").rstrip(".")
    return text.replace(",", " ").replace(".", ",")


def fmt_pct(value, signed: bool = True) -> str:
    """Проценты с одним знаком после запятой: «+20,0%»."""
    if value is None or pd.isna(value):
        return EMPTY
    text = f"{abs(float(value)):.1f}".replace(".", ",")
    sign = ("+" if value >= 0 else "−") if signed else ""
    return f"{sign}{text}%"


def fmt_date(iso) -> str:
    """«2025-09-30» -> «30.09.2025»; всё остальное возвращается как есть."""
    try:
        return date.fromisoformat(str(iso)).strftime("%d.%m.%Y")
    except ValueError:
        return str(iso)


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(color_a: str, color_b: str) -> float:
    """Контраст двух цветов по WCAG (нужно не меньше 4,5 для обычного текста)."""
    hi, lo = sorted((_luminance(color_a), _luminance(color_b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# ---------- связанные строки и признак «ИИ помог» ----------
def attach_context(issues: pd.DataFrame, items: pd.DataFrame, ai_keys: set) -> pd.DataFrame:
    """Добавляет к расхождениям колонки sources (где смотреть: список строк «Роль · файл · лист «…» · строка N») и ai_matched.

    Источник расхождения всегда строка акта; к нему добавляются документы, с которыми сравнивали: ВОР и остальные строки актов по ключу
    для превышения объёма, смета для роста цены, договор для акта после срока."""
    issues = issues.copy()
    sources, ai = [], []
    for _, r in issues.iterrows():
        own = ("act", r["source_file"], r["source_sheet"], int(r["source_row"]))
        found = [own]
        same = items[items["work_key"] == r["work_key"]] if r["work_key"] else items.iloc[0:0]

        def pick(doc_type, only_first=True):
            part = same[same["doc_type"] == doc_type].sort_values(["source_file", "source_row"])
            part = part.head(1) if only_first else part
            return [(doc_type, p.source_file, p.source_sheet, int(p.source_row)) for p in part.itertuples()]

        if r["issue_type"] == "volume_exceeded":
            found += pick("vor") + [x for x in pick("act", False) if x != own]
        elif r["issue_type"] == "price_increase":
            found += pick("estimate")
        elif r["issue_type"] == "late_act":
            contract = items[items["doc_type"] == "contract"].head(1)
            found += [("contract", p.source_file, p.source_sheet, int(p.source_row)) for p in contract.itertuples()]
        sources.append([f"{SOURCE_ROLE[t]} · {f} · лист «{s}» · строка {n}" for t, f, s, n in found])
        ai.append(r["issue_type"] in ("volume_exceeded", "price_increase") and r["work_key"] in ai_keys)
    issues["sources"] = sources
    issues["ai_matched"] = ai
    return issues


# ---------- сводные числа ----------
def impact_split(issues: pd.DataFrame) -> dict:
    """Сумма влияния на бюджет по высокой и низкой уверенности (пустое влияние считается нулём) и число расхождений низкой уверенности."""
    if issues.empty:
        return {"high": 0.0, "low": 0.0, "n_low": 0}
    amount = issues["impact_som"].fillna(0)
    low = issues["confidence"] == "low"
    return {"high": float(amount[~low].sum()), "low": float(amount[low].sum()), "n_low": int(low.sum())}


def headline_metrics(summary: dict, issues: pd.DataFrame) -> dict:
    """Четыре карточки: позиций проверено, расхождений, влияние на бюджет, расхождений высокой важности (проверить в первую очередь).

    Влияние: в режиме llm общая сумма из summary; в режиме без ИИ крупно только высокая уверенность, остальное отдельно (мелко)."""
    split = impact_split(issues)
    llm = summary["mode"] == "llm"
    return {"positions": summary["n"], "issues": summary["z"],
            "impact": summary["impact_som"] if llm else split["high"],
            "impact_extra_n": 0 if llm else split["n_low"], "impact_extra": 0.0 if llm else split["low"],
            "manual": int((issues["severity"] == "high").sum()) if not issues.empty else 0}


def traffic_segments(summary: dict) -> list:
    """Три сегмента светофора из summary['statuses']: [{status, count, word, bg, fg, label}]."""
    out = []
    for status in ("red", "yellow", "green"):
        bg, fg = STATUS_COLORS[status]
        count = int(summary["statuses"][status])
        out.append({"status": status, "count": count, "word": STATUS_PLURAL[status], "bg": bg, "fg": fg,
                    "label": f"{STATUS_PLURAL[status]}: {count} {_positions_word(count)}"})
    return out


def _positions_word(n: int) -> str:
    if 11 <= n % 100 <= 14:
        return "позиций"
    return {1: "позиция", 2: "позиции", 3: "позиции", 4: "позиции"}.get(n % 10, "позиций")


def traffic_legend() -> str:
    """Пояснение цветов по docs/synthetic_spec.md §6; допуски берутся из config/rules.yaml, не хардкодятся."""
    rules = load_config()["rules"]
    over = rules["volume_exceeded"]["tolerance_pct"]
    under = rules["position_status"]["green_under_tolerance_pct"]
    return (f"Красный: есть возможное расхождение по позиции или факт по актам больше плана более чем на {fmt_num(over)} %. "
            f"Жёлтый: факт меньше плана более чем на {fmt_num(under)} % (работа идёт или пара ещё не найдена). "
            "Зелёный: факт в пределах допуска.")


def chart_frames(issues: pd.DataFrame) -> tuple:
    """-> (по типам: число расхождений, по типам: влияние на бюджет). Все четыре типа всегда присутствуют, подписи готовые строки."""
    counts, impacts = [], []
    for t in TYPE_ORDER:
        part = issues[issues["issue_type"] == t] if not issues.empty else issues
        n = int(len(part))
        amount = float(part["impact_som"].fillna(0).sum()) if n else 0.0
        counts.append({"label": TYPE_CHART_RU[t], "value": n, "text": str(n)})
        impacts.append({"label": TYPE_CHART_RU[t], "value": amount, "text": fmt_num(amount)})
    return pd.DataFrame(counts), pd.DataFrame(impacts)


# ---------- карточки расхождений ----------
def issue_phrase(r) -> str:
    """Одна понятная фраза «что не так» с числами из полей issues_view (expected, actual, delta_pct, unit, expected_text, actual_text)."""
    unit = r["unit"] or ""
    kind = r["issue_type"]
    if kind == "volume_exceeded":
        return (f"В актах {fmt_num(r['actual'])} {unit} при {fmt_num(r['expected'])} {unit} в ВОР ({fmt_pct(r['delta_pct'])})").replace("  ", " ")
    if kind == "price_increase":
        if pd.isna(r["expected"]):
            return f"Цена в акте {fmt_num(r['actual'])} сом за {unit}; цены в смете для сравнения нет"
        return (f"Цена в акте {fmt_num(r['actual'])} сом за {unit} при {fmt_num(r['expected'])} сом в смете "
                f"({fmt_pct(r['delta_pct'])})")
    if kind == "missing_in_vor":
        return f"Позиция есть в актах ({fmt_num(r['actual'])} {unit}), но в ВОР пары не найдено".replace("  ", " ")
    return (f"Акт датирован {fmt_date(r['actual_text'])}, срок договора {fmt_date(r['expected_text'])}: "
            f"позже срока на {fmt_num(r['actual'])} дн.")


def sort_issues(issues: pd.DataFrame) -> pd.DataFrame:
    """Сначала высокая важность, внутри по влиянию на бюджет по убыванию (пустое влияние в конце группы)."""
    if issues.empty:
        return issues
    rank = issues["severity"].map({s: i for i, s in enumerate(SEVERITY_ORDER)})
    keyed = issues.assign(_rank=rank, _impact=issues["impact_som"].fillna(-1))
    return keyed.sort_values(["_rank", "_impact", "issue_id"], ascending=[True, False, True]).drop(columns=["_rank", "_impact"])


def filter_issues(issues: pd.DataFrame, positions: pd.DataFrame, severity: str = "all", types=None, query: str = "") -> pd.DataFrame:
    """Фильтры экрана: важность (high/medium/low/all), типы (список issue_type или пусто = все), поиск по названию работы."""
    out = issues
    if severity != "all":
        out = out[out["severity"] == severity]
    if types:
        out = out[out["issue_type"].isin(types)]
    if query.strip():
        names = _titles(out, positions)
        mask = names.str.contains(query.strip(), case=False, regex=False)
        out = out[mask.values]
    return out


def _titles(issues: pd.DataFrame, positions: pd.DataFrame) -> pd.Series:
    names = dict(zip(positions["work_key"], positions["name"])) if not positions.empty else {}
    titles = []
    for _, r in issues.iterrows():
        if r["issue_type"] == "late_act":
            titles.append(f"Акт {r['source_file']} после срока договора")
        else:
            titles.append(names.get(r["work_key"]) or (r["work_key"] or EMPTY))
    return pd.Series(titles, index=issues.index, dtype="object")


def build_cards(issues: pd.DataFrame, positions: pd.DataFrame) -> list:
    """Карточки расхождений в порядке датафрейма (отсортируй sort_issues заранее)."""
    titles = _titles(issues, positions)
    cards = []
    for idx, r in issues.iterrows():
        if pd.isna(r["impact_som"]):
            impact = f"{EMPTY} ({r['impact_note']})" if r["impact_note"] else EMPTY
        else:
            impact = f"{fmt_num(r['impact_som'])} сом"
        if r["confidence"] == "low":
            note = LOW_CONFIDENCE_NOTE
        elif r["issue_type"] == "missing_in_vor":
            note = AI_NOT_FOUND_NOTE
        else:
            note = ""
        cards.append({"issue_id": int(r["issue_id"]), "title": titles[idx], "type": r["issue_type"], "type_label": TYPE_RU[r["issue_type"]],
                      "severity": r["severity"], "severity_label": SEVERITY_RU[r["severity"]], "phrase": issue_phrase(r),
                      "impact_text": impact, "impact_value": None if pd.isna(r["impact_som"]) else float(r["impact_som"]),
                      "sources": list(r["sources"]), "ai": bool(r["ai_matched"]), "note": note})
    return cards


def cards_frame(cards: list) -> pd.DataFrame:
    """Те же карточки таблицей: влияние числом (для форматирования колонки), источники в одну колонку."""
    return pd.DataFrame([{"Важность": c["severity_label"], "Тип": c["type_label"], "Работа": c["title"], "Что не так": c["phrase"],
                          "Влияние, сом": c["impact_value"], "Источник": "\n".join(c["sources"]),
                          "ИИ помог сопоставить": "да" if c["ai"] else "", "Пометка": c["note"]} for c in cards],
                        columns=["Важность", "Тип", "Работа", "Что не так", "Влияние, сом", "Источник", "ИИ помог сопоставить", "Пометка"])


# ---------- светофор по позициям ----------
def positions_view(positions: pd.DataFrame, status: str = "all") -> pd.DataFrame:
    """Таблица позиций: красные сверху; колонка Статус словом. Служебная колонка _status нужна только для подсветки строк."""
    cols = ["Работа", "Ед.", "План", "Факт", "Выполнено, %", "Статус", "_status"]
    if positions.empty:
        return pd.DataFrame(columns=cols)
    out = positions if status == "all" else positions[positions["status"] == status]
    rank = out["status"].map({"red": 0, "yellow": 1, "green": 2})
    out = out.assign(_rank=rank).sort_values(["_rank", "name"])
    return pd.DataFrame({"Работа": out["name"].values, "Ед.": out["unit_label"].values, "План": out["plan_qty"].values,
                         "Факт": out["fact_qty"].values, "Выполнено, %": out["pct"].values,
                         "Статус": out["status"].map(STATUS_SINGULAR).values, "_status": out["status"].values}, columns=cols)
