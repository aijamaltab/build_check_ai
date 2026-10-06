"""Страница «Демо»: итог сверки демо-проекта (режим с ИИ, ответы из кэша) и вход на проверку своих файлов."""
import streamlit as st

from ui import components as ui
from ui.loader import build_demo
from ui.screens import blocks

HERO_TITLE = "Находит расхождения между ВОР, сметой, договором и актами"
AI_NOTE = "ИИ читает и сопоставляет названия, код считает и проверяет числа"


def render(upload_page=None, results_page=None) -> None:
    ui.render(ui.hero_html(HERO_TITLE, AI_NOTE, "Демо на синтетических данных"))
    try:
        results = build_demo("llm")
    except Exception:  # noqa: BLE001: пользователю человеческая ошибка, подробности в логе
        st.error("Не удалось собрать результат из демо-проекта. Обновите страницу; если ошибка повторяется, сообщите разработчикам.")
        return
    summary, issues, positions = results["summary"], results["issues"], results["positions"]
    if not results["n_files"] or not summary:
        st.error("Файлы демо-проекта не найдены, сверять нечего.")
        return
    if summary["mode"] != "llm":                          # кэша нет: pipeline сам перешёл на правила
        ui.render(ui.banner_html(summary["banner"] or "ИИ-режим недоступен, использован базовый режим"))

    blocks.metrics_block(summary, issues, positions)
    blocks.traffic_block(summary)
    blocks.top_issues_block(issues, positions)
    if upload_page is not None:
        st.page_link(upload_page, label="Проверить свои файлы", icon=":material/upload_file:")
    if results_page is not None:
        st.page_link(results_page, label="Открыть сверочную ведомость →")
    blocks.footer()
