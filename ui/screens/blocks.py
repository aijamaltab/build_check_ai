"""Общие блоки страниц: метрики, светофор, карточки расхождений, позиции, отчёт. Страницы только собирают их вместе."""
import streamlit as st

from ui import components as ui
from ui.data import (TYPE_ORDER, TYPE_RU, build_cards, cards_frame, chart_frames, filter_issues, fmt_num, headline_metrics, positions_view,
                     sort_issues, traffic_legend, traffic_segments)

SEVERITY_CHOICES = {"Все": "all", "Высокая": "high", "Средняя": "medium", "Низкая": "low"}
STATUS_CHOICES = {"Все": "all", "Красные": "red", "Жёлтые": "yellow", "Зелёные": "green"}
COLOR_MAP = {"Красные": "red", "Жёлтые": "yellow", "Зелёные": "green"}
FOOTER = '<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>'
TOP_N = 5
ROWS_LABEL = "Строк в документах"
ROWS_NOTE = "ВОР, смета и акты, без договора"


def footer() -> None:
    ui.render(FOOTER)


def metrics_block(summary: dict, issues, positions) -> None:
    """Четыре метрики. Первая это строки документов (summary['n']), а не позиции светофора: их число показано рядом со светофором."""
    m = headline_metrics(summary, issues, positions)
    ui.render(ui.metric_cards_html([
        {"label": ROWS_LABEL, "value": fmt_num(m["positions"]), "note": ROWS_NOTE},
        {"label": "Возможных расхождений", "value": fmt_num(m["issues"])},
        {"label": "Возможное влияние на бюджет, сом", "value": fmt_num(m["impact"]), "note": "Оценка размера возможных расхождений, не вывод о потерях"},
        {"label": "Позиции с отклонением от плана", "value": fmt_num(m["review_positions"]),
         "note": "красные и жёлтые позиции: расхождение или выполнение меньше плана"}]))
    if m["impact_extra_n"]:
        ui.render(f'<div class="note-small">В сумму не входят ещё {m["impact_extra_n"]} расхождений низкой уверенности '
                  f'(без ИИ), возможное влияние {fmt_num(m["impact_extra"])} сом.</div>')


def traffic_block(summary: dict) -> None:
    """Полоса светофора и легенда (один раз на странице)."""
    total = sum(int(v) for v in summary["statuses"].values())
    ui.render(ui.section_html("Светофор по позициям", f"Позиций ВОР в светофоре: {total}"))
    ui.render(ui.traffic_html(traffic_segments(summary)))
    ui.render(f'<div class="legend">{traffic_legend()}</div>')
    if summary.get("caveat"):
        ui.render(ui.banner_html(summary["caveat"]))


def top_issues_block(issues, positions, n: int = TOP_N) -> None:
    """Главные расхождения: сначала высокая важность, внутри по влиянию на бюджет."""
    ui.render(ui.section_html("Главные расхождения", f"{min(n, len(issues))} из {len(issues)}: сначала высокая важность, внутри по влиянию на бюджет. "
                                                      "Каждое расхождение требует проверки специалистом."))
    if issues.empty:
        st.info("Расхождений не найдено.")
        return
    ui.render(ui.cards_html(build_cards(sort_issues(issues).head(n), positions)))


def issues_block(issues, positions, key: str = "") -> None:
    """Графики по типам и список расхождений с фильтрами; переключатель «Карточки/Таблица»."""
    by_count, by_impact = chart_frames(issues)
    left, right = st.columns(2)
    with left:
        ui.render(ui.section_html("Расхождения по типам"))
        ui.bar_chart(by_count)
    with right:
        ui.render(ui.section_html("Влияние на бюджет по типам, сом"))
        ui.bar_chart(by_impact)

    ui.render(ui.section_html("Возможные расхождения",
                              "Сначала высокая важность, внутри по влиянию на бюджет. В каждой карточке слева то, что в ВОР, смете или договоре, "
                              "справа то, что в акте, как написано в файлах. Каждое расхождение требует проверки специалистом."))
    view = ui.segmented("Вид", ["Карточки", "Таблица"], "Карточки", f"{key}view")
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        severity = SEVERITY_CHOICES[ui.segmented("Важность", list(SEVERITY_CHOICES), "Все", f"{key}severity")]
    with c2:
        chosen = st.multiselect("Тип", [TYPE_RU[t] for t in TYPE_ORDER], placeholder="Все типы", key=f"{key}type_filter")
    with c3:
        query = st.text_input("Поиск по названию работы", placeholder="например, арматура", key=f"{key}query_filter")
    types = [t for t in TYPE_ORDER if TYPE_RU[t] in chosen]
    cards_list = build_cards(sort_issues(filter_issues(issues, positions, severity, types, query)), positions)
    st.caption(f"Показано {len(cards_list)} из {len(issues)}")
    if not cards_list:
        st.info("По выбранным фильтрам расхождений нет.")
    elif view == "Карточки":
        ui.render(ui.cards_html(cards_list))
    else:
        ui.stretch(st.dataframe, cards_frame(cards_list), hide_index=True, height=max(500, 36 * len(cards_list) + 40),
                   column_config={"Влияние, сом": st.column_config.NumberColumn("Влияние, сом", format="localized"),
                                  "Источник": st.column_config.TextColumn("Источник", width="large"),
                                  "Что не так": st.column_config.TextColumn("Что не так", width="large")})


def positions_block(summary: dict, positions) -> None:
    """Позиции со светофором: полоса с легендой, поиск и фильтры, таблица."""
    if positions is None or positions.empty:
        st.info("Данные по позициям отсутствуют.")
        return
    if summary and "statuses" in summary:
        traffic_block(summary)
    ui.render(ui.section_html("Поиск и фильтры", "Найдите работу по названию или отфильтруйте по цветам и единицам измерения."))
    col_q, col_chk = st.columns([3, 2])
    with col_q:
        query = st.text_input("Поиск по названию позиции", placeholder="например, бетон, кровля или арматура", key="positions_query")
    with col_chk:
        st.write("")
        st.write("")
        only_review = st.checkbox("Только позиции с отклонением от плана (красные и жёлтые)", value=False, key="positions_only_review")
    col_col, col_unit = st.columns([2, 2])
    with col_col:
        chosen_colors = st.multiselect("Цвет светофора", options=list(COLOR_MAP), key="positions_colors", disabled=only_review,
                                       placeholder="Все цвета" if not only_review else "Красные и жёлтые")
    with col_unit:
        units = sorted(u for u in positions["unit_label"].dropna().unique() if str(u).strip())
        chosen_units = st.multiselect("Единица измерения", options=units, placeholder="Все единицы", key="positions_units")

    filtered = positions.copy()
    if query and query.strip():
        filtered = filtered[filtered["name"].str.contains(query.strip(), case=False, na=False)]
    if only_review:
        filtered = filtered[filtered["status"].isin(["red", "yellow"])]
    elif chosen_colors:
        filtered = filtered[filtered["status"].isin([COLOR_MAP[c] for c in chosen_colors])]
    if chosen_units:
        filtered = filtered[filtered["unit_label"].isin(chosen_units)]
    st.caption(f"Показано {len(filtered)} из {len(positions)} позиций")
    if filtered.empty:
        st.info("По выбранным критериям позиций не найдено. Попробуйте сбросить фильтры.")
        return
    table = positions_view(filtered)
    ui.stretch(st.dataframe, ui.style_positions(table), hide_index=True, height=min(650, 36 * len(table) + 42),
               column_config={"Работа": st.column_config.TextColumn("Работа", width="large"),
                              "Ед.": st.column_config.TextColumn("Ед.", width="small"),
                              "План": st.column_config.TextColumn("План", width="small"),
                              "Факт": st.column_config.TextColumn("Факт", width="small"),
                              "Выполнено, %": st.column_config.TextColumn("Выполнено, %", width="small"),
                              "Статус": st.column_config.TextColumn("Статус", width="small")})
    st.caption("На мобильных устройствах таблица прокручивается по горизонтали.")
