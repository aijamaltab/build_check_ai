"""Страница «Загрузить свои файлы»: сверка пользовательских документов."""
import tempfile
from pathlib import Path

import streamlit as st

from src.config import load_config
from src.pipeline import run_pipeline
from ui import components as ui
from ui.data import (TYPE_ORDER, TYPE_RU, build_cards, cards_frame, chart_frames, describe_file, file_label, file_preview, filter_issues,
                     fmt_num, headline_metrics, load_results, positions_view, sort_issues, traffic_legend, traffic_segments)

SEVERITY_CHOICES = {"Все": "all", "Высокая": "high", "Средняя": "medium", "Низкая": "low"}
STATUS_CHOICES = {"Все": "all", "Красные": "red", "Жёлтые": "yellow", "Зелёные": "green"}
HERO_TITLE = "Загрузите свои файлы для сверки"
HERO_LEAD = "Загрузите ВОР, смету, договор и акты в формате Excel (.xlsx), чтобы система сопоставила их и нашла возможные расхождения."
AI_NOTE = "Для новых названий ИИ-ответов в демо-кэше нет, такие строки останутся «неоднозначными»"


def render_files(results: dict, source_dir: Path) -> None:
    """Выбор файла проекта: структура и просмотр."""
    ui.render(ui.section_html("Исходные файлы", "Выберите файл, чтобы увидеть, что программа в нём распознала."))
    files = results.get("files")
    if files is None or files.empty:
        st.info("Список распознанных файлов пуст.")
        return
    labels = [file_label(r) for _, r in files.iterrows()]
    choice = st.selectbox("Файл", labels, key="upload_file_choice", label_visibility="collapsed")
    if not choice:
        return
    row = files.iloc[labels.index(choice)]
    ui.render(ui.fileinfo_html(describe_file(row, load_config()["templates"])))
    path = source_dir / row["file_name"]
    if not path.exists():
        st.info("Файл для просмотра не найден на диске.")
        return
    try:
        preview = file_preview(path)
    except Exception:
        st.info("Не удалось загрузить предварительный просмотр для этого файла.")
        return
    st.caption(f"Лист «{preview['sheet']}», как в файле: показаны строки 1–{preview['shown']} из {preview['n_rows']}, "
               f"колонки A–{preview['frame'].columns[-1] if preview['n_cols'] else 'A'}. "
               f"Цифры слева — номера строк Excel.")
    letters = [c for c in preview["frame"].columns if c != "Строка"]
    ui.stretch(st.dataframe, preview["frame"], hide_index=True, height=min(520, 36 * preview["shown"] + 44),
               column_config={"Строка": st.column_config.NumberColumn("Строка", width="small"),
                              **{c: st.column_config.TextColumn(c, width="medium") for c in letters}})


def render() -> None:
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD, "Ваши данные", AI_NOTE))

    st.info("Для новых названий ИИ-ответов в демо-кэше нет, такие строки не сопоставлены, "
            "позиции могут быть показаны неверно и требуют проверки.")

    with st.expander("Как подготовить файлы", expanded=False):
        st.write("""
        1. **ВОР (Ведомость объёмов работ):** Обязательно. Поддерживается один или несколько файлов. Содержит наименования работ, единицы измерения и объёмы.
        2. **Смета:** Необязательно. Используется для сверки цен за единицу.
        3. **Договор:** Необязательно. Используется для проверки срока выполнения работ и даты закрытия актов.
        4. **Акты выполненных работ:** Обязательно. Один или несколько файлов (по мотивам КС-2).
        5. **Формат:** Только Excel (.xlsx).
        """)

    col1, col2, col3 = st.columns(3)
    with col1:
        vor_files = st.file_uploader("ВОР (.xlsx)", type=["xlsx"], accept_multiple_files=True,
                                     key="upload_vor", help="Один или несколько файлов ведомости объёмов работ (обязательно)")
    with col2:
        estimate_file = st.file_uploader("Смета (.xlsx, необязательно)", type=["xlsx"],
                                         key="upload_estimate", help="Смета в текущих ценах")
        contract_file = st.file_uploader("Договор (.xlsx, необязательно)", type=["xlsx"],
                                         key="upload_contract", help="Договор с указанием срока и общей суммы")
    with col3:
        act_files = st.file_uploader("Акты выполненных работ (.xlsx)", type=["xlsx"], accept_multiple_files=True,
                                     key="upload_acts", help="Один или несколько актов выполненных работ (обязательно)")

    if st.button("Сверить", type="primary"):
        if not vor_files and not act_files:
            st.error("Пожалуйста, загрузите ведомость объёмов работ (ВОР) и хотя бы один акт выполненных работ.")
            return
        if not vor_files:
            st.error("Пожалуйста, загрузите хотя бы один файл ВОР (ведомость объёмов работ).")
            return
        if not act_files:
            st.error("Пожалуйста, загрузите хотя бы один акт выполненных работ.")
            return

        tmp_dir = Path(tempfile.mkdtemp(prefix="buildcheck_upload_"))
        st.session_state["upload_dir"] = tmp_dir

        try:
            for vor in vor_files:
                (tmp_dir / vor.name).write_bytes(vor.getbuffer())
            if estimate_file:
                (tmp_dir / estimate_file.name).write_bytes(estimate_file.getbuffer())
            if contract_file:
                (tmp_dir / contract_file.name).write_bytes(contract_file.getbuffer())
            for act in act_files:
                (tmp_dir / act.name).write_bytes(act.getbuffer())

            db_path = tmp_dir / "upload.db"

            with st.spinner("Сверяем документы…"):
                summary = run_pipeline(str(tmp_dir), db_path, mode="llm", project_id="upload")
                results = load_results(db_path, project_id="upload")
                results["n_files"] = summary["files"]

                st.session_state["upload_results"] = results
                st.session_state["upload_summary"] = summary
        except Exception as exc:
            st.error(f"Не удалось выполнить сверку документов: {exc}. Проверьте формат файлов и структуру таблиц.")
            return

    if "upload_results" in st.session_state:
        results = st.session_state["upload_results"]
        summary = st.session_state["upload_summary"]
        source_dir = st.session_state.get("upload_dir")

        if not summary or summary.get("files", 0) == 0 or results.get("files", None) is None or results["files"].empty:
            st.error("Загруженные файлы не были распознаны. Убедитесь, что они сохранены в формате .xlsx и содержат строки заголовков с наименованием, единицей измерения и количеством.")
            if summary.get("documents_with_errors"):
                st.warning(f"Файлы с ошибками при чтении: {', '.join(summary['documents_with_errors'])}")
            return

        if summary.get("documents_with_errors"):
            st.warning(f"Некоторые файлы не удалось распознать (проверьте структуру колонок): {', '.join(summary['documents_with_errors'])}")

        if source_dir:
            render_files(results, source_dir)

        issues, positions = results["issues"], results["positions"]
        actual = summary["mode"]

        ui.render(ui.section_html("Результат сверки", "Итог по загруженным файлам."))
        if actual != "llm":
            ui.render(ui.banner_html(summary["banner"] or "ИИ-режим недоступен, использован базовый режим"))

        m = headline_metrics(summary, issues, positions)
        cards = [{"label": "Позиций проверено", "value": fmt_num(m["positions"])},
                 {"label": "Возможных расхождений", "value": fmt_num(m["issues"])},
                 {"label": "Возможное влияние на бюджет, сом", "value": fmt_num(m["impact"]),
                  "note": "Оценка размера возможных расхождений, не вывод о потерях"},
                 {"label": "Позиции с отклонением от плана", "value": fmt_num(m["review_positions"]),
                  "note": "красные и жёлтые позиции: расхождение или выполнение меньше плана"}]
        ui.render(ui.metric_cards_html(cards))
        if m["impact_extra_n"]:
            ui.render(f'<div class="note-small">В сумму не входят ещё {m["impact_extra_n"]} расхождений низкой уверенности '
                      f'(без ИИ), возможное влияние {fmt_num(m["impact_extra"])} сом.</div>')

        ai = summary.get("ai", {})
        if actual == "llm" and ai.get("pairs_no_decision", 0) + ai.get("rows_no_decision", 0) > 0:
            ui.render(f'<div class="note-small">ИИ-ответы из кэша демо; для новых названий {ai.get("rows_no_decision", 0)} строк требуют проверки.</div>')

        ui.render(ui.section_html("Светофор по позициям"))
        ui.render(ui.traffic_html(traffic_segments(summary)))
        ui.render(f'<div class="legend">{traffic_legend()}</div>')
        if summary.get("caveat"):
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
        view = ui.segmented("Вид", ["Карточки", "Таблица"], "Карточки", "upload_view")
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            severity = SEVERITY_CHOICES[ui.segmented("Важность", list(SEVERITY_CHOICES), "Все", "upload_severity")]
        with c2:
            chosen = st.multiselect("Тип", [TYPE_RU[t] for t in TYPE_ORDER], placeholder="Все типы", key="upload_type_filter")
        with c3:
            query = st.text_input("Поиск по названию работы", placeholder="например, арматура", key="upload_query_filter")

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
        status = STATUS_CHOICES[ui.segmented("Цвет", list(STATUS_CHOICES), "Все", "upload_status")]
        ui.stretch(st.dataframe, ui.style_positions(positions_view(positions, status)), hide_index=True, height=500)

    ui.render('<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>')
