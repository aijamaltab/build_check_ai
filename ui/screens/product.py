"""Страница «Программа»: продукт для инженеров. Исходные файлы проекта и итог сверки по ним (режим с ИИ, ответы из кэша)."""
from pathlib import Path

import streamlit as st

from src.config import load_config
from ui import components as ui
from ui.data import (TYPE_ORDER, TYPE_RU, build_cards, cards_frame, chart_frames, describe_file, file_label, file_preview, filter_issues,
                     fmt_num, headline_metrics, positions_view, sort_issues, traffic_legend, traffic_segments)
from ui.loader import DEMO_DIR, build_demo

SEVERITY_CHOICES = {"Все": "all", "Высокая": "high", "Средняя": "medium", "Низкая": "low"}
STATUS_CHOICES = {"Все": "all", "Красные": "red", "Жёлтые": "yellow", "Зелёные": "green"}
HERO_TITLE = "Находит расхождения между ВОР, сметой, договором и актами"
HERO_LEAD = ("На входе Excel-документы объекта, на выходе список возможных расхождений с указанием файла, листа и строки. "
             "Ниже разбор демо-проекта: исходные файлы и итог сверки по ним.")
AI_NOTE = "ИИ читает и сопоставляет названия, код считает и проверяет числа"
BENEFITS = [("Четыре документа в одной таблице",
             "ВОР, смета, договор и акты приводятся к единой таблице: единицы измерения и названия работ сопоставляются между документами."),
            ("У каждого расхождения есть источник",
             "Файл, лист и строка: специалист открывает документ и проверяет сам. Система показывает возможное расхождение, а не выносит вердикт."),
            ("Оценка влияния на бюджет",
             "Возможное влияние в сомах считает код по данным документов. Это оценка размера расхождения, а не вывод о потерях.")]


def render_files(results: dict) -> None:
    """Выбор файла проекта: структура (документ, шаблон, колонки, что прочитано) и сам лист как в Excel."""
    ui.render(ui.section_html("Исходные файлы", f"Девять Excel-файлов демо-проекта: ВОР, смета, договор и акты. Выберите файл, чтобы увидеть, "
                                                "как он выглядит и что программа в нём распознала."))
    files = results["files"]
    if files.empty:
        st.info("Список файлов недоступен.")
        return
    labels = [file_label(r) for _, r in files.iterrows()]
    choice = st.selectbox("Файл", labels, key="file_choice", label_visibility="collapsed")
    row = files.iloc[labels.index(choice)]
    ui.render(ui.fileinfo_html(describe_file(row, load_config()["templates"])))
    path = Path(DEMO_DIR) / row["file_name"]
    if not path.exists():
        st.info("Файл для просмотра не найден.")
        return
    preview = file_preview(path)
    st.caption(f"Лист «{preview['sheet']}», как в файле: показаны строки 1–{preview['shown']} из {preview['n_rows']}, колонки A–"
               f"{preview['frame'].columns[-1] if preview['n_cols'] else 'A'}. Цифры слева это номера строк Excel.")
    letters = [c for c in preview["frame"].columns if c != "Строка"]
    ui.stretch(st.dataframe, preview["frame"], hide_index=True, height=min(520, 36 * preview["shown"] + 44),
               column_config={"Строка": st.column_config.NumberColumn("Строка", width="small"),
                              **{c: st.column_config.TextColumn(c, width="medium") for c in letters}})


def render(rationale_page=None) -> None:
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD, "Демо на синтетических данных", AI_NOTE))
    ui.render(ui.trio_html(BENEFITS))
    if rationale_page is not None:
        st.page_link(rationale_page, label="Почему здесь нужен ИИ: сравнение с ИИ и без →")

    try:
        results = build_demo("llm")
    except Exception:  # noqa: BLE001: пользователю человеческая ошибка, подробности в логе
        st.error("Не удалось собрать результат из демо-проекта. Обновите страницу; если ошибка повторяется, сообщите разработчикам.")
        return
    summary, issues, positions = results["summary"], results["issues"], results["positions"]
    if not results["n_files"] or not summary:
        st.error("Файлы демо-проекта не найдены, сверять нечего.")
        return
    actual = summary["mode"]

    render_files(results)

    ui.render(ui.section_html("Результат сверки: капремонт школы", "Итог по всем девяти файлам. Документы синтетические."))
    if actual != "llm":                                  # кэша нет: pipeline сам перешёл на правила
        ui.render(ui.banner_html(summary["banner"] or "ИИ-режим недоступен, использован базовый режим"))

    m = headline_metrics(summary, issues, positions)
    cards = [{"label": "Позиций проверено", "value": fmt_num(m["positions"])},
             {"label": "Возможных расхождений", "value": fmt_num(m["issues"])},
             {"label": "Возможное влияние на бюджет, сом", "value": fmt_num(m["impact"]),
              "note": "Оценка размера возможных расхождений, не вывод о потерях"},
             {"label": "Позиции для проверки", "value": fmt_num(m["review_positions"]), "note": "красные и жёлтые позиции"}]
    ui.render(ui.metric_cards_html(cards))
    if m["impact_extra_n"]:
        ui.render(f'<div class="note-small">В сумму не входят ещё {m["impact_extra_n"]} расхождений низкой уверенности '
                  f'(без ИИ), возможное влияние {fmt_num(m["impact_extra"])} сом.</div>')
    ai = summary["ai"]
    if actual == "llm" and ai["pairs_no_decision"] + ai["rows_no_decision"] > 0:
        ui.render(f'<div class="note-small">ИИ-ответы из кэша демо; для новых названий {ai["rows_no_decision"]} строк требуют проверки.</div>')

    ui.render(ui.section_html("Светофор по позициям"))
    ui.render(ui.traffic_html(traffic_segments(summary)))
    ui.render(f'<div class="legend">{traffic_legend()}</div>')
    if summary["caveat"]:
        ui.render(ui.banner_html(summary["caveat"]))

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
    view = ui.segmented("Вид", ["Карточки", "Таблица"], "Карточки", "view")
    c1, c2, c3 = st.columns([2, 2, 2])
    with c1:
        severity = SEVERITY_CHOICES[ui.segmented("Важность", list(SEVERITY_CHOICES), "Все", "severity")]
    with c2:
        chosen = st.multiselect("Тип", [TYPE_RU[t] for t in TYPE_ORDER], placeholder="Все типы")
    with c3:
        query = st.text_input("Поиск по названию работы", placeholder="например, арматура")
    types = [t for t in TYPE_ORDER if TYPE_RU[t] in chosen]
    shown = sort_issues(filter_issues(issues, positions, severity, types, query))
    cards_list = build_cards(shown, positions)
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

    ui.render(ui.section_html("Позиции", "Красные сверху. Цвет подкреплён словом в колонке «Статус»."))
    status = STATUS_CHOICES[ui.segmented("Цвет", list(STATUS_CHOICES), "Все", "status")]
    ui.stretch(st.dataframe, ui.style_positions(positions_view(positions, status)), hide_index=True, height=500)

    ui.render('<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>')
