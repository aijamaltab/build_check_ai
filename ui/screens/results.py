"""Страница «Все результаты»: расхождения, позиции и отчёт по демо-проекту или по загруженным файлам (вкладки)."""
import streamlit as st

from ui import components as ui
from ui.loader import build_demo
from ui.screens import blocks
from ui.screens.report import render_report

HERO_TITLE = "Все результаты сверки"
HERO_LEAD = "Полный список расхождений, позиции со светофором и отчёт для скачивания."


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
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD, "Результаты"))
    picked = pick_results()
    if picked is None:
        return
    results, summary = picked
    issues, positions = results.get("issues"), results.get("positions")
    if issues is None or positions is None:
        st.info("Данных для показа нет.")
        return
    tab_issues, tab_positions, tab_report = st.tabs(["Расхождения", "Позиции", "Отчёт"])
    with tab_issues:
        blocks.issues_block(issues, positions)
    with tab_positions:
        blocks.positions_block(summary, positions)
    with tab_report:
        render_report(issues, positions)
    blocks.footer()
