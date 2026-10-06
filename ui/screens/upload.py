"""Страница «Загрузить свои файлы»: сверка пользовательских документов."""
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from src.pipeline import run_pipeline
from ui import components as ui
from ui.data import load_results
from ui.screens import blocks
from ui.screens.report import download_button

MAX_FILE_MB = 5
HERO_TITLE = "Загрузите свои файлы для сверки"
HERO_LEAD = "Загрузите ВОР, смету, договор и акты в формате Excel (.xlsx), чтобы система сопоставила их и нашла возможные расхождения."


def render(results_page=None) -> None:
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD, "Ваши данные"))

    st.info("Для новых названий ИИ-ответов в демо-кэше нет, такие строки не сопоставлены, "
            "позиции могут быть показаны неверно и требуют проверки.")

    with st.expander("Как подготовить файлы", expanded=False):
        st.write("""
        1. **ВОР (Ведомость объёмов работ):** Обязательно. Поддерживается один или несколько файлов. Содержит наименования работ, единицы измерения и объёмы.
        2. **Смета:** Необязательно. Используется для сверки цен за единицу.
        3. **Договор:** Необязательно. Используется для проверки срока выполнения работ и даты закрытия актов.
        4. **Акты выполненных работ:** Обязательно. Один или несколько файлов (по мотивам КС-2).
        5. **Формат:** только Excel (.xlsx), не больше 5 МБ на файл.
        """)

    st.caption(f"Только .xlsx, не больше {MAX_FILE_MB} МБ на файл.")
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
        chosen = [*vor_files, *([estimate_file] if estimate_file else []), *([contract_file] if contract_file else []), *act_files]
        if not vor_files and not act_files:
            st.error("Пожалуйста, загрузите ведомость объёмов работ (ВОР) и хотя бы один акт выполненных работ.")
        elif not vor_files:
            st.error("Пожалуйста, загрузите хотя бы один файл ВОР (ведомость объёмов работ).")
        elif not act_files:
            st.error("Пожалуйста, загрузите хотя бы один акт выполненных работ.")
        elif problems := file_problems(chosen):
            for text in problems:
                st.error(text)
        else:
            run_reconciliation(chosen)

    if "upload_results" in st.session_state:
        show_result(st.session_state["upload_results"], st.session_state["upload_summary"], results_page)
    blocks.footer()


def file_problems(files: list) -> list:
    """Сообщения о файлах не .xlsx и больше лимита (st.file_uploader размер сам не ограничивает)."""
    out = []
    for f in files:
        if not f.name.lower().endswith(".xlsx"):
            out.append(f"Файл «{f.name}» не в формате .xlsx. Загрузите Excel-файл (.xlsx).")
        elif f.size > MAX_FILE_MB * 1024 * 1024:
            out.append(f"Файл «{f.name}» больше {MAX_FILE_MB} МБ ({f.size / 1024 / 1024:.1f} МБ). Уменьшите файл или загрузите другой.")
    return out


def run_reconciliation(files: list) -> None:
    """Сверка во временной папке; результат уходит в session_state, папка удаляется после обработки."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="buildcheck_upload_"))
    try:
        for f in files:
            (tmp_dir / Path(f.name).name).write_bytes(f.getbuffer())
        with st.spinner("Сверяем документы…"):
            summary = run_pipeline(str(tmp_dir), tmp_dir / "upload.db", mode="llm", project_id="upload")
            results = load_results(tmp_dir / "upload.db", project_id="upload")
            results["n_files"] = summary["files"]
        st.session_state["upload_results"] = results
        st.session_state["upload_summary"] = summary
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось выполнить сверку документов: {exc}. Проверьте формат файлов и структуру таблиц.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def show_result(results: dict, summary: dict, results_page=None) -> None:
    if not summary or summary.get("files", 0) == 0 or results.get("files", None) is None or results["files"].empty:
        st.error("Загруженные файлы не были распознаны. Убедитесь, что они сохранены в формате .xlsx и содержат строки заголовков "
                 "с наименованием, единицей измерения и количеством.")
        if summary and summary.get("documents_with_errors"):
            st.warning(f"Файлы с ошибками при чтении: {', '.join(summary['documents_with_errors'])}")
        return
    if summary.get("documents_with_errors"):
        st.warning(f"Некоторые файлы не удалось распознать (проверьте структуру колонок): {', '.join(summary['documents_with_errors'])}")
    issues, positions = results["issues"], results["positions"]
    ui.render(ui.section_html("Результат сверки", "Итог по загруженным файлам."))
    if summary["mode"] != "llm":
        ui.render(ui.banner_html(summary["banner"] or "ИИ-режим недоступен, использован базовый режим"))
    blocks.metrics_block(summary, issues, positions)
    blocks.traffic_block(summary)
    blocks.top_issues_block(issues, positions)
    download_button(issues, positions, key="upload_report")
    if results_page is not None:
        st.page_link(results_page, label="Все расхождения и позиции →")
