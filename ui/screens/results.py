"""Страница «Сверочная ведомость»: таблица позиций (демо-проект или загруженные файлы) и вкладка «Отчёт»."""
import streamlit as st

from ui import components as ui
from ui.loader import build_demo
from ui.screens import blocks
from ui.screens.report import render_report

HERO_TITLE = "Сверочная ведомость"
HERO_LEAD = "Строка — позиция ВОР. Нажмите на подсвеченную ячейку или строку: источники и объяснение."


def pick_results():
    """-> (results, summary) демо-проекта или загруженных файлов (если они есть в сессии и выбраны); None при ошибке."""
    uploaded = st.session_state.get("upload_results")
    if uploaded is not None:
        c_src, _ = st.columns([2, 4])
        with c_src:
            source = ui.segmented("Источник данных", ["Демо-проект", "Загруженные файлы"], "Загруженные файлы", "results_source")
        if source == "Загруженные файлы":
            return uploaded, st.session_state.get("upload_summary", uploaded.get("summary", {}))
    try:
        results = build_demo("llm")
    except Exception:  # noqa: BLE001
        st.error("Не удалось загрузить данные демо-проекта.")
        return None
    return results, results["summary"]


def render() -> None:
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD, "Только чтение"))
    picked = pick_results()
    if picked is None:
        return
    results, summary = picked
    if results.get("issues") is None or results.get("positions") is None:
        st.info("Данных для показа нет.")
        return
    tab_ledger, tab_report = st.tabs(["Ведомость", "Отчёт"])
    with tab_ledger:
        blocks.ledger_block(results)
    with tab_report:
        render_report(results["issues"], results["positions"])
    blocks.footer()
