"""Страница «Результаты»: шапка и три вкладки (Сводка, Расхождения, Позиции) по последнему прогону сессии."""
import pandas as pd
import streamlit as st

from ui import components as ui
from ui import runner
from ui.data import (SEVERITY_ORDER, SEVERITY_RU, TYPE_ORDER, TYPE_RU, build_cards, cards_frame, chart_frames, filter_issues, fmt_num,
                     sort_issues)
from ui.live_ai import describe_ai
from ui.ledger_data import summary_points
from ui.screens import blocks
from ui.screens.empty import empty_state
from ui.screens.report import download_button

HERO_TITLE = "Результаты сверки"
CACHE_NOTE = "Результат собран из сохранённых ответов ИИ"
MAX_CARDS = 50
ALL = "Все"
VIEW_TABLE, VIEW_CARDS = "Таблица", "Карточки"
TABLE_COLUMNS = ["Важность", "Тип", "Работа", "Что не так", "Влияние, сом", "Источник", "Пометка"]


def header(run: dict, upload_page, rationale_page) -> None:
    summary = run["summary"]
    ui.render(ui.hero_html(HERO_TITLE, run["label"], runner.mode_label(run)))
    if summary["mode"] != "llm":
        ui.render(ui.banner_html(summary.get("banner") or "ИИ-режим недоступен, использован базовый режим"))
    if run.get("set_name"):                                      # демо-набор: живых запросов нет, только кэш
        ui.render(f'<div class="note-small">{CACHE_NOTE}</div>')
    else:
        ai = describe_ai(summary, run.get("live", False))
        ui.render(f'<div class="note-small">{ui.escape(ai["line"])}</div>')
        if ai["stopped"]:
            st.warning(ai["stopped"])
    if summary.get("documents_with_errors"):
        st.warning(f"Некоторые файлы не удалось распознать (проверьте структуру колонок): {', '.join(summary['documents_with_errors'])}")
    c_dl, c_new, c_ai = st.columns([2, 1.4, 2])
    with c_dl:
        download_button(run["results"]["issues"], run["results"]["positions"], key="results_report")
    with c_new:
        if upload_page is not None:
            st.page_link(upload_page, label="Новая загрузка")
    with c_ai:
        if rationale_page is not None:
            st.page_link(rationale_page, label="Как работает ИИ →")


def summary_tab(run: dict) -> None:
    results, summary = run["results"], run["summary"]
    blocks.metrics_block(summary, results["issues"], results["positions"])
    blocks.traffic_block(summary)
    counts, impacts = chart_frames(results["issues"])
    c1, c2 = st.columns(2)
    with c1:
        ui.render(ui.section_html("Расхождения по типам", "Число возможных расхождений"))
        ui.bar_chart(counts)
    with c2:
        ui.render(ui.section_html("Влияние по типам, сом", "Оценка размера возможных расхождений"))
        ui.bar_chart(impacts)
    ui.render(ui.section_html("Итоги сверки"))
    points = summary_points(results, run.get("compare"))
    ui.render('<ul class="summary-list">' + "".join(f"<li>{ui.escape(p)}</li>" for p in points) + "</ul>")


def issues_tab(run: dict) -> None:
    results = run["results"]
    issues, positions = results["issues"], results["positions"]
    if issues.empty:
        st.info("Расхождений не найдено.")
        return
    c_sev, c_type, c_q = st.columns([2, 3, 2])
    with c_sev:
        sev_label = st.selectbox("Важность", [ALL] + [SEVERITY_RU[s] for s in SEVERITY_ORDER], key="flt_severity")
    with c_type:
        types = st.multiselect("Тип расхождения", TYPE_ORDER, format_func=lambda t: TYPE_RU[t], key="flt_types", placeholder="Все типы")
    with c_q:
        query = st.text_input("Поиск по названию работы", key="flt_query")
    severity = next((s for s in SEVERITY_ORDER if SEVERITY_RU[s] == sev_label), "all")
    chosen = sort_issues(filter_issues(issues, positions, severity=severity, types=types, query=query))
    view = ui.segmented("Вид", [VIEW_TABLE, VIEW_CARDS], VIEW_TABLE, key="issues_view")
    shown = len(chosen) if view == VIEW_TABLE else min(len(chosen), MAX_CARDS)
    ui.render(ui.section_html("Возможные расхождения", f"Показано {shown} из {len(issues)}. "
                                                       "Сначала высокая важность, внутри по влиянию на бюджет. Каждое требует проверки специалистом."))
    if chosen.empty:
        st.info("По выбранным фильтрам расхождений нет.")
        return
    if view == VIEW_CARDS:
        ui.render(ui.cards_html(build_cards(chosen.head(MAX_CARDS), positions)))
        return
    frame = cards_frame(build_cards(chosen, positions))[TABLE_COLUMNS].copy()
    frame["Источник"] = frame["Источник"].str.replace(chr(10), "; ", regex=False)
    frame["Влияние, сом"] = frame["Влияние, сом"].map(lambda v: fmt_num(v) if pd.notna(v) else "—")
    ui.render(ui.html_table(frame))


def positions_tab(run: dict) -> None:
    ui.render(ui.section_html("Позиции со светофором", "Строка — позиция ВОР. Нажмите на подсвеченную ячейку или строку: источники и объяснение."))
    blocks.ledger_block(run["results"])


def render(upload_page=None, rationale_page=None) -> None:
    run = runner.current_run()
    if run is None:
        ui.render(ui.hero_html(HERO_TITLE, "Здесь появится итог сверки после загрузки файлов или запуска демо-набора."))
        empty_state(upload_page, key="results")
        blocks.footer()
        return
    header(run, upload_page, rationale_page)
    tab_summary, tab_issues, tab_positions = st.tabs(["Сводка", "Расхождения", "Позиции"])
    with tab_summary:
        summary_tab(run)
    with tab_issues:
        issues_tab(run)
    with tab_positions:
        positions_tab(run)
    blocks.footer()
