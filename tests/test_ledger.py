"""Сверочная ведомость: подготовка данных (ui/ledger_data.py) и HTML таблицы (ui/ledger.py), без Streamlit и без браузера."""
import json
from pathlib import Path

import pytest

from src.pipeline import run_pipeline
from tests.cache_guard import REAL_CACHE
from ui.data import STATUS_COLORS, contrast_ratio, fmt_run_at, load_results
from ui.ledger import COLUMN_TITLES, ledger_html
from ui.ledger_data import build_issue_rows, build_ledger, summary_points

DEMO_DIR = Path(__file__).resolve().parents[1] / "data" / "synthetic"


@pytest.fixture(scope="module")
def ledger(tmp_path_factory):
    import os
    old = {k: os.environ.get(k) for k in ("LLM_CACHE_DIR", "LLM_CACHE_ONLY", "GEMINI_API_KEY")}
    os.environ.update(LLM_CACHE_DIR=str(REAL_CACHE), LLM_CACHE_ONLY="1")
    os.environ.pop("GEMINI_API_KEY", None)
    try:
        db = tmp_path_factory.mktemp("ledger") / "demo.db"
        run_pipeline(DEMO_DIR, db, mode="llm")
        return build_ledger(load_results(db))
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def row(ledger, text):
    return next(r for r in ledger["rows"] if text.lower() in r["name"].lower())


def test_one_row_per_position_with_traffic_light_counts(ledger):
    assert ledger["total"] == len(ledger["rows"]) == 48
    counts = {s: sum(r["status"] == s for r in ledger["rows"]) for s in ("red", "yellow", "green")}
    assert counts == {"red": 11, "yellow": 7, "green": 30}
    assert [r["n"] for r in ledger["rows"]] == list(range(1, 49))
    assert {"м2", "м3", "т"} <= set(ledger["units"])


def test_only_cells_with_a_discrepancy_are_highlighted(ledger):
    assert all(not r["hl"] for r in ledger["rows"] if r["status"] == "green")        # зелёные строки нейтральные
    assert all(r["hl"]["status"] == r["status"] for r in ledger["rows"] if r["status"] != "green")
    assert set(ledger["rows"][0]["hl"]) == set()
    volume = row(ledger, "Арматура А500 d12")
    assert volume["hl"] == {"fact": "red", "pct": "red", "status": "red"}               # объём: только «Акты» и «Выполнено», цена нейтральная
    price = row(ledger, "Кладка кирпичных стен")
    assert price["hl"] == {"est": "red", "actp": "red", "dp": "red", "status": "red"}   # цена: три колонки цены
    assert (price["est"], price["actp"], price["dp"]) == ("6 200", "6 900", "+11,3%")
    missing = row(ledger, "видеонаблюдения")
    assert missing["hl"]["name"] == "red" and missing["hl"]["fact"] == "red" and missing["plan"] == "—"
    under = row(ledger, "Укладка линолеума")
    assert under["hl"] == {"fact": "yellow", "pct": "yellow", "status": "yellow"}


def test_status_has_word_and_arrow_not_only_colour(ledger):
    assert row(ledger, "Арматура А500 d12")["arrow"] == "up" and row(ledger, "Арматура А500 d12")["status_ru"] == "Красный"
    assert row(ledger, "Укладка линолеума")["arrow"] == "down" and row(ledger, "Укладка линолеума")["status_ru"] == "Жёлтый"
    assert row(ledger, "видеонаблюдения")["arrow"] == "up"
    assert row(ledger, "Кладка кирпичных стен")["arrow"] == ""
    assert row(ledger, "Разработка грунта экскаватором")["status_ru"] == "Зелёный"


def test_tooltip_has_file_sheet_row_values_impact_and_ai_mark(ledger):
    tip = row(ledger, "Бетон М300")["tips"]["fact"]
    assert tip["title"] == "Превышение объёма" and "Отклонение: +15,3% (допуск 5 %)" in tip["facts"]
    assert "ВОР · vor_1.xlsx · лист «ВОР» · строка 19" in tip["sources"] and any(s.startswith("Акт · act_2.xlsx") for s in tip["sources"])
    assert tip["impact"] == "101 400 сом" and tip["ai"].startswith("ИИ сопоставил названия (уверенность 0,95")
    price = row(ledger, "Установка окон ПВХ")["tips"]["actp"]
    assert price["title"] == "Рост цены" and any(s.startswith("Смета · estimate.xlsx") for s in price["sources"]) and price["impact"] == "121 000 сом"
    assert "уверенность" in price["ai"]


def test_row_details_list_all_sources_issues_and_documents(ledger):
    r = row(ledger, "Арматура А500 d12")
    assert set(r["sources"]) == {"ВОР", "Смета", "Акты"} and len(r["sources"]["Акты"]) == 2
    assert r["issues"][0]["type"] == "Превышение объёма" and "Требует проверки" in r["issues"][0]["text"]
    assert r["files"] == ["act_1.xlsx", "act_2.xlsx", "estimate.xlsx", "vor_1.xlsx"]
    assert not row(ledger, "Разработка грунта экскаватором")["issues"]


def test_document_level_issues_are_listed_separately(ledger):
    assert [i["type"] for i in ledger["doc_issues"]] == ["Акт после срока"] * 2
    assert all("Договор · contract.xlsx" in " ".join(i["sources"]) for i in ledger["doc_issues"])


def test_ledger_is_json_serializable_and_has_no_nan(ledger):
    text = json.dumps(ledger, ensure_ascii=False, allow_nan=False)
    assert "NaN" not in text


def test_html_has_columns_filters_and_safe_data(ledger):
    html = ledger_html({**ledger, "rows": [{**ledger["rows"][0], "name": "</script><b>x"}]})
    assert html.count("</script>") == 2                                  # данные не закрывают тег script
    assert "<\\/script>" in html
    for title in COLUMN_TITLES:
        assert title in html
    for text in ("Только позиции с отклонением от плана", "Только расхождения", "Поиск по названию", "Все единицы"):
        assert text in html
    assert "Только позиции для проверки" not in html
    assert "IBM Plex Sans" in html and "tabular-nums" in html and "height:34px" in html and "position:sticky" in html
    assert "border-radius:6px" in html and "gradient" not in html and "serif" not in html.replace("sans-serif", "")


def test_status_colors_and_contrast():
    assert [STATUS_COLORS[s][0] for s in ("red", "yellow", "green")] == ["#C62828", "#F9A825", "#2E7D32"]
    for fill in ("#FDECEA", "#FFF6DB", "#FFFFFF"):                      # тёмный текст на светлых заливках ячеек
        assert contrast_ratio("#1B2733", fill) >= 4.5


def test_run_date_format():
    assert fmt_run_at("2026-10-06T19:04:39") == "06.10.2026 19:04" and fmt_run_at(None) == "—"


def test_column_order_pinned_columns_and_price_hint(ledger):
    assert COLUMN_TITLES[:3] == ["№", "Статус", "Наименование (по ВОР)"] and "Цена по акту (средняя)" in COLUMN_TITLES
    assert "Цена по акту" not in [t for t in COLUMN_TITLES if t != "Цена по акту (средняя)"]
    html = ledger_html(ledger)
    assert '"k": "n"' in html and html.index('"k": "status"') < html.index('"k": "name"')
    assert "Средневзвешенная по количеству, если актов несколько" in html
    for col in (".c-n", ".c-status", ".c-name"):                          # колонки закреплены слева
        assert col in html
    assert "position:sticky; background:#fff" in html


def test_sidebar_is_collapsed_by_default():
    from pathlib import Path as P
    assert 'initial_sidebar_state="collapsed"' in (P(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")


def test_price_delta_is_dash_unless_there_is_a_price_issue(ledger):
    assert row(ledger, "Кладка кирпичных стен")["dp"] == "+11,3%"
    assert row(ledger, "Разработка грунта экскаватором")["dp"] == "—"
    assert all(r["dp"] == "—" for r in ledger["rows"] if "est" not in r["hl"])
    assert not any(r["dp"] in ("0,0%", "+0,0%", "−0,0%") for r in ledger["rows"])


@pytest.fixture(scope="module")
def both(tmp_path_factory):
    import os
    old = {k: os.environ.get(k) for k in ("LLM_CACHE_DIR", "LLM_CACHE_ONLY", "GEMINI_API_KEY")}
    os.environ.update(LLM_CACHE_DIR=str(REAL_CACHE), LLM_CACHE_ONLY="1")
    os.environ.pop("GEMINI_API_KEY", None)
    try:
        d = tmp_path_factory.mktemp("both")
        run_pipeline(DEMO_DIR, d / "a.db", mode="llm")
        run_pipeline(DEMO_DIR, d / "b.db", mode="rules_only")
        return load_results(d / "a.db"), load_results(d / "b.db")
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


def test_issue_rows_only_discrepancies_sorted_with_readable_phrase(both):
    rows = build_issue_rows(both[0])["rows"]
    assert len(rows) == 13 and [r["n"] for r in rows] == list(range(1, 14))
    assert [r["impact"] for r in rows[:3]] == ["240 000", "210 000", "195 000"]
    beton = next(r for r in rows if "Бетон М300" in r["name"])
    assert beton["text"] == "В актах 98 м3, в ВОР 85 м3, на 15,3 % больше при допуске 5 %" and beton["type"] == "Превышение объёма"
    assert "ВОР · vor_1.xlsx · лист «ВОР» · строка 19" in beton["where"] and beton["ai_badge"] is True      # где смотреть и значок ИИ
    assert not next(r for r in rows if "Арматура А500" in r["name"])["ai_badge"]
    tip = beton["tips"]["text"]
    assert tip["impact"] == "101 400 сом" and tip["sources"] == beton["where"] and tip["ai"].startswith("ИИ сопоставил названия")
    assert set(beton["tips"]) == {"n", "type", "name", "text", "impact", "where"}                       # подсказка на любой ячейке строки
    assert {r["type"] for r in rows} == {"Превышение объёма", "Рост цены", "Нет в ВОР", "Акт после срока"}


def test_issue_table_html_mode_has_columns_and_no_clipping_css(both):
    html = ledger_html(build_issue_rows(both[0]), "issues")
    for title in ("Тип", "Работа", "Что не сходится", "Влияние, сом", "Где смотреть"):
        assert f'"title": "{title}"' in html
    assert "mode-issues" in html and "ellipsis" not in html and "overflow:hidden" not in html.replace(" ", "")
    assert "data-label" in html and '"mode": "issues"' in html


def test_summary_points_come_from_data(both):
    points = summary_points(*both)
    assert len(points) == 5
    assert points[0] == "Найдено 13 возможных расхождений по 11 позициям и 2 документам (акт после срока)."
    assert points[1] == "Чаще всего: превышение объёма (5)."
    assert "1 378 030 сом" in points[2] and points[3].startswith("Проверить первыми: Монтаж системы видеонаблюдения (240 000 сом); Устройство цементной")
    assert points[4] == "Без ИИ было бы 18 расхождений, из них 10 ложных; с ИИ 13, из них ложных 1."


def test_html_table_escapes_and_labels_cells():
    import pandas as pd
    from ui.components import chain_html, html_table
    t = html_table(pd.DataFrame({"А": ["<b>x</b>"], "Б": ["y"]}))
    assert "&lt;b&gt;" in t and 'data-label="А"' in t and "<b>x" not in t
    ex = [{"kind": "pair_rejected", "vor": None, "doc": "д", "code_rule": "р", "ai": "и (уверенность 0,50)", "code_check": "к"},
          {"kind": "row_none", "vor": "в", "doc": "д", "code_rule": "р", "ai": "и", "code_check": "к"}]
    c = chain_html(ex)
    assert "✕ отклонено" in c and "✓ принято" in c and "<th>Что решил ИИ (уверенность)</th>" in c and "—" in c


def test_chain_header_arrows_use_the_arrow_character():
    from ui.styles import CSS
    assert 'content: "→"' in CSS and "\x11" not in CSS                 # стрелка между заголовками цепочки, а не управляющий символ
    assert "text-overflow" not in CSS.replace("text-overflow: clip", "")
