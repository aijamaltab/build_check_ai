"""Страница «Главная»: сценарий «файлы демо-проекта -> сверить -> результат и итоги»."""
from pathlib import Path

import streamlit as st

from ui import components as ui
from ui.data import fmt_num
from ui.ledger_data import summary_points
from ui.loader import DEMO_DIR, build_demo
from ui.screens import blocks

TITLE = "Сверка строительных документов"
LEAD = "Сопоставляет ВОР, смету, договор и акты и показывает возможные расхождения со ссылкой на файл, лист и строку"
STEPS = ["Приводит четыре документа к одной таблице", "ИИ сопоставляет названия, код считает объёмы и цены",
         "Показывает возможные расхождения и их влияние на бюджет в сомах"]
VOR_NOTE = "ВОР: ведомость объёмов работ, список работ и их объёмов по проекту"
ROLE_RU = {"vor": "ВОР", "estimate": "Смета", "contract": "Договор", "act": "Акты"}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
RUN_KEY = "home_run"
CACHE_NOTE = "Результат собран из сохранённых ответов ИИ (демо-режим, ключ не используется)"


def reset() -> None:
    st.session_state[RUN_KEY] = False


def files_block(files) -> None:
    ui.render(ui.section_html("Демо-проект: файлы", "Капремонт школы, девять Excel-файлов. Данные демо синтетические."))
    with st.container(key="demo_files"):
        head = st.columns([1.1, 2.2, 1.0, 1.9])
        for col, text in zip(head, ("Роль", "Файл", "Позиций", "")):
            col.markdown(f"**{text}**" if text else "")
        for _, f in files.iterrows():
            c1, c2, c3, c4 = st.columns([1.1, 2.2, 1.0, 1.9])
            c1.markdown(ROLE_RU.get(f["doc_type"], f["doc_type"]))
            c2.markdown(f["file_name"])
            c3.markdown(fmt_num(f["n_rows_read"]))
            path = Path(DEMO_DIR) / f["file_name"]
            if path.exists():
                c4.download_button("Скачать", path.read_bytes(), file_name=f["file_name"], mime=XLSX, key=f"dl_{f['file_name']}")


def render(upload_page=None, ledger_page=None, rationale_page=None) -> None:
    ui.render(ui.hero_html(TITLE, LEAD))
    ui.render(ui.steps_html(STEPS, VOR_NOTE))
    try:
        results = build_demo("llm")
    except Exception:  # noqa: BLE001: пользователю человеческая ошибка, подробности в логе
        st.error("Не удалось собрать результат из демо-проекта. Обновите страницу; если ошибка повторяется, сообщите разработчикам.")
        return
    summary, issues, positions = results["summary"], results["issues"], results["positions"]
    if not results["n_files"] or not summary:
        st.error("Файлы демо-проекта не найдены, сверять нечего.")
        return

    files_block(results["files"])
    if not st.session_state.get(RUN_KEY):
        if st.button("Загрузить файлы в систему и сверить", type="primary", width="stretch", key="home_start"):
            st.session_state[RUN_KEY] = True
            st.rerun()
        blocks.footer()
        return

    c_note, c_reset = st.columns([5, 1])
    with c_note:
        if summary["mode"] == "llm":
            ui.render(f'<div class="note-small">{CACHE_NOTE}</div>')
        else:
            ui.render(ui.banner_html(summary["banner"] or "ИИ-режим недоступен, использован базовый режим"))
    with c_reset:
        st.button("Начать заново", on_click=reset, key="home_reset")

    blocks.metrics_block(summary, issues, positions)
    blocks.traffic_block(summary)
    ui.render(ui.section_html("Возможные расхождения", "Сначала высокая важность, внутри по влиянию на бюджет. Нажмите на строку, чтобы увидеть детали."))
    blocks.issues_table_block(results)

    ui.render(ui.section_html("Итоги сверки"))
    points = summary_points(results, build_demo("rules_only"))
    ui.render('<ul class="summary-list">' + "".join(f"<li>{ui.escape(p)}</li>" for p in points) + "</ul>")
    if rationale_page is not None:
        st.page_link(rationale_page, label="Как работает ИИ: сравнение с ИИ и без →")
    c1, c2 = st.columns(2)
    with c1:
        if ledger_page is not None:
            st.page_link(ledger_page, label="Открыть полную сверочную ведомость")
    with c2:
        if upload_page is not None:
            st.page_link(upload_page, label="Проверить свои файлы")
    blocks.footer()
