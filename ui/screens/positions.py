"""Страница «Позиции»: поиск и расширенные фильтры по позициям со светофором."""
import streamlit as st

from ui import components as ui
from ui.data import STATUS_SINGULAR, fmt_num, load_results, positions_view, traffic_legend, traffic_segments
from ui.loader import build_demo

COLOR_MAP = {"Красные": "red", "Жёлтые": "yellow", "Зелёные": "green"}
HERO_TITLE = "Позиции ведомости и выполнение"
HERO_LEAD = ("Сводный список всех позиций объекта: план по ведомости объёмов работ (ВОР), "
             "накопительный факт по актам выполненных работ, процент выполнения и статус светофора.")
AI_NOTE = "Красный — расхождение или перерасход; Жёлтый — недовыполнение; Зелёный — в пределах плана"


def render() -> None:
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD, "Светофор позиций", AI_NOTE))

    # Выбор источника данных, если в сессии есть загруженные файлы
    if "upload_results" in st.session_state:
        c_src, _ = st.columns([2, 4])
        with c_src:
            source = ui.segmented("Источник данных", ["Демо-проект", "Загруженные файлы"], "Демо-проект", "positions_source")
        if source == "Загруженные файлы":
            results = st.session_state["upload_results"]
            summary = st.session_state.get("upload_summary", results.get("summary", {}))
        else:
            try:
                results = build_demo("llm")
                summary = results["summary"]
            except Exception:
                st.error("Не удалось загрузить данные демо-проекта.")
                return
    else:
        try:
            results = build_demo("llm")
            summary = results["summary"]
        except Exception:
            st.error("Не удалось загрузить данные демо-проекта.")
            return

    positions = results.get("positions")
    if positions is None or positions.empty:
        st.info("Данные по позициям отсутствуют.")
        return

    # Светофор и легенда
    if summary and "statuses" in summary:
        ui.render(ui.section_html("Светофор по позициям"))
        ui.render(ui.traffic_html(traffic_segments(summary)))
        ui.render(f'<div class="legend">{traffic_legend()}</div>')
        if summary.get("caveat"):
            ui.render(ui.banner_html(summary["caveat"]))

    ui.render(ui.section_html("Поиск и фильтры", "Найдите работу по названию или отфильтруйте по цветам и единицам измерения."))

    # Панель фильтров
    col_q, col_chk = st.columns([3, 2])
    with col_q:
        query = st.text_input("Поиск по названию позиции", placeholder="например, бетон, кровля или арматура", key="positions_query")
    with col_chk:
        st.write("")  # вертикальный отступ для выравнивания с полем ввода
        st.write("")
        only_review = st.checkbox("Только позиции для проверки (красные и жёлтые)", value=False, key="positions_only_review")

    col_col, col_unit = st.columns([2, 2])
    with col_col:
        color_choices = list(COLOR_MAP.keys())
        chosen_colors = st.multiselect("Цвет светофора", options=color_choices,
                                       placeholder="Все цвета" if not only_review else "Красные и жёлтые",
                                       key="positions_colors",
                                       disabled=only_review)
    with col_unit:
        available_units = sorted([u for u in positions["unit_label"].dropna().unique() if str(u).strip()])
        chosen_units = st.multiselect("Единица измерения", options=available_units, placeholder="Все единицы", key="positions_units")

    # Применение фильтров
    filtered = positions.copy()

    if query and query.strip():
        filtered = filtered[filtered["name"].str.contains(query.strip(), case=False, na=False)]

    if only_review:
        filtered = filtered[filtered["status"].isin(["red", "yellow"])]
    elif chosen_colors:
        selected_statuses = [COLOR_MAP[c] for c in chosen_colors if c in COLOR_MAP]
        if selected_statuses:
            filtered = filtered[filtered["status"].isin(selected_statuses)]

    if chosen_units:
        filtered = filtered[filtered["unit_label"].isin(chosen_units)]

    st.caption(f"Показано {len(filtered)} из {len(positions)} позиций")

    if filtered.empty:
        st.info("По выбранным критериям позиций не найдено. Попробуйте сбросить фильтры.")
    else:
        table = positions_view(filtered)
        ui.stretch(st.dataframe, ui.style_positions(table), hide_index=True,
                   height=min(650, 36 * len(table) + 42),
                   column_config={"Работа": st.column_config.TextColumn("Работа", width="large"),
                                  "Ед.": st.column_config.TextColumn("Ед.", width="small"),
                                  "План": st.column_config.TextColumn("План", width="small"),
                                  "Факт": st.column_config.TextColumn("Факт", width="small"),
                                  "Выполнено, %": st.column_config.TextColumn("Выполнено, %", width="small"),
                                  "Статус": st.column_config.TextColumn("Статус", width="small")})
        st.caption("На мобильных устройствах таблица прокручивается по горизонтали.")

    ui.render('<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>')
