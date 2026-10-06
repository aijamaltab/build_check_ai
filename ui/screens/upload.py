"""Страница «Проверить свои файлы»: сверка пользовательских документов и готовых наборов, при наличии ключа с живым ИИ."""
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from src.config import load_config
from src.llm.budget import CallBudget
from src.pipeline import run_pipeline
from ui import components as ui
from ui.data import load_results
from ui.ledger_data import summary_points
from ui.live_ai import (MAX_FILE_MB, MAX_FILES, PRIVACY_WARNING, SESSION_LIMIT, SITE_DAILY_LIMIT, build_live_ai, describe_ai, get_api_key,
                        scrub)
from ui.screens import blocks
from ui.screens.report import download_button
from ui.sets import SETS, set_files, zip_bytes

HERO_TITLE = "Проверить свои файлы"
HERO_LEAD = "Загрузите ВОР, смету, договор и акты в формате Excel (.xlsx): система сопоставит их и покажет возможные расхождения."
LIVE_INFO = ("Новые названия, для которых нет сохранённого ответа, разбирает ИИ в реальном времени. "
             f"Лимиты: до {SESSION_LIMIT} запросов на сессию, до {SITE_DAILY_LIMIT} в сутки на весь сайт, не дольше 90 секунд на прогон.")
OFFLINE_INFO = ("Ключ ИИ на этом сайте не настроен: используются только сохранённые ответы ИИ. "
                "Для новых названий ответов нет, такие строки не сопоставлены, позиции могут быть показаны неверно и требуют проверки.")


@st.cache_resource
def site_budget() -> CallBudget:
    """Общий суточный счётчик живых запросов: один на процесс, то есть на всех посетителей."""
    return CallBudget(SITE_DAILY_LIMIT, daily=True)


@st.cache_data(show_spinner=False)
def cached_zip(name: str) -> bytes:
    return zip_bytes(name)


def api_key() -> str | None:
    try:
        secrets = st.secrets
    except Exception:  # noqa: BLE001
        secrets = None
    return get_api_key(secrets)


def session_budget() -> CallBudget:
    if "live_budget" not in st.session_state:               # в session_state только счётчик, ключа там нет
        st.session_state["live_budget"] = CallBudget(SESSION_LIMIT)
    return st.session_state["live_budget"]


def file_problems(files: list) -> list:
    """Сообщения о числе файлов, не .xlsx и больше лимита (st.file_uploader размер сам не ограничивает)."""
    out = []
    if len(files) > MAX_FILES:
        out.append(f"Загружено файлов: {len(files)}, максимум {MAX_FILES}. Оставьте самые нужные (ВОР, акты, смету, договор).")
    for f in files:
        if not f.name.lower().endswith(".xlsx"):
            out.append(f"Файл «{f.name}» не в формате .xlsx. Загрузите Excel-файл (.xlsx).")
        elif f.size > MAX_FILE_MB * 1024 * 1024:
            out.append(f"Файл «{f.name}» больше {MAX_FILE_MB} МБ ({f.size / 1024 / 1024:.1f} МБ). Уменьшите файл или загрузите другой.")
    return out


def run_reconciliation(source: Path, label: str) -> None:
    """Сверка папки. База лежит во временной папке, она удаляется после обработки.
    Прогресс настоящий: счётчики приходят из судей по мере разбора пар и строк."""
    key = api_key()
    cfg = load_config()
    bar = st.progress(0.0, text="Читаем файлы и сопоставляем названия…")
    status = st.empty()
    labels = {"pairs": "пар названий", "rows": "строк без пары"}

    def progress(stage, done, total):
        bar.progress(min(1.0, done / total) if total else 1.0, text=f"Разобрано {done} из {total} {labels[stage]}")
        status.markdown(f"Разобрано {done} из {total} {labels[stage]}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="buildcheck_upload_"))
    try:
        judge, row_matcher, live = build_live_ai(cfg, key, session_budget(), site_budget(), progress)
        summary = run_pipeline(str(source), tmp_dir / "upload.db", mode="llm", judge=judge, row_matcher=row_matcher, project_id="upload", cfg=cfg)
        results = load_results(tmp_dir / "upload.db", project_id="upload")
        results["n_files"] = summary["files"]
        st.session_state.update(upload_results=results, upload_summary=summary, upload_live=live, upload_label=label)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось выполнить сверку документов: {scrub(exc, key)}. Проверьте формат файлов и структуру таблиц.")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        bar.empty()
        status.empty()


def run_uploaded(files: list) -> None:
    """Копирует загруженные файлы во временную папку, сверяет и удаляет её."""
    folder = Path(tempfile.mkdtemp(prefix="buildcheck_files_"))
    try:
        for f in files:
            (folder / Path(f.name).name).write_bytes(f.getbuffer())
        run_reconciliation(folder, "загруженные файлы")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def sets_block() -> None:
    ui.render(ui.section_html("Готовые наборы для проверки", "Синтетические данные. Девять файлов в каждом наборе, названия работ в них системе не знакомы."))
    for name, title in SETS.items():
        files = set_files(name)
        if not files:
            continue
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.markdown(f"**{title}**")
        c2.download_button("Скачать набор (zip)", cached_zip(name), file_name=f"{name}.zip", mime="application/zip", key=f"zip_{name}")
        if c3.button("Сверить этот набор", key=f"run_{name}"):
            run_reconciliation(files[0].parent, title)


def show_result(results: dict, summary: dict, live: bool = False) -> None:
    if not summary or summary.get("files", 0) == 0 or results.get("files", None) is None or results["files"].empty:
        st.error("Загруженные файлы не были распознаны. Убедитесь, что они сохранены в формате .xlsx и содержат строки заголовков "
                 "с наименованием, единицей измерения и количеством.")
        if summary and summary.get("documents_with_errors"):
            st.warning(f"Файлы с ошибками при чтении: {', '.join(summary['documents_with_errors'])}")
        return
    if summary.get("documents_with_errors"):
        st.warning(f"Некоторые файлы не удалось распознать (проверьте структуру колонок): {', '.join(summary['documents_with_errors'])}")
    issues, positions = results["issues"], results["positions"]
    ui.render(ui.section_html("Результат сверки", st.session_state.get("upload_label", "")))
    if summary["mode"] != "llm":
        ui.render(ui.banner_html(summary["banner"] or "ИИ-режим недоступен, использован базовый режим"))
    ai = describe_ai(summary, live)
    ui.render(f'<div class="note-small">{ui.escape(ai["line"])}</div>')
    if ai["stopped"]:
        st.warning(ai["stopped"])
    blocks.metrics_block(summary, issues, positions)
    blocks.traffic_block(summary)
    ui.render(ui.section_html("Возможные расхождения", "Нажмите на строку, чтобы увидеть детали."))
    blocks.issues_table_block(results)
    ui.render(ui.section_html("Итоги сверки"))
    ui.render('<ul class="summary-list">' + "".join(f"<li>{ui.escape(p)}</li>" for p in summary_points(results)) + "</ul>")
    download_button(issues, positions, key="upload_report")


def render() -> None:
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD))
    live = bool(api_key())
    if live:
        st.warning(PRIVACY_WARNING)
        st.info(LIVE_INFO)
    else:
        st.info(OFFLINE_INFO)

    with st.expander("Как подготовить файлы", expanded=False):
        st.write(f"""
        1. **ВОР (ведомость объёмов работ):** обязательно, один или несколько файлов.
        2. **Смета:** необязательно, один или несколько файлов, нужна для сверки цен за единицу.
        3. **Договор:** необязательно, нужен для проверки срока выполнения работ.
        4. **Акты выполненных работ:** обязательно, один или несколько файлов.
        5. **Формат и размер:** только Excel (.xlsx), не больше {MAX_FILE_MB} МБ на файл, не больше {MAX_FILES} файлов за один раз.
        """)

    st.caption(f"Только .xlsx, не больше {MAX_FILE_MB} МБ на файл, не больше {MAX_FILES} файлов.")
    col1, col2, col3 = st.columns(3)
    with col1:
        vor_files = st.file_uploader("ВОР (.xlsx)", type=["xlsx"], accept_multiple_files=True, key="upload_vor",
                                     help="Один или несколько файлов ведомости объёмов работ (обязательно)")
    with col2:
        estimate_files = st.file_uploader("Смета (.xlsx, необязательно)", type=["xlsx"], accept_multiple_files=True, key="upload_estimate",
                                          help="Один или несколько файлов сметы в текущих ценах")
        contract_file = st.file_uploader("Договор (.xlsx, необязательно)", type=["xlsx"], key="upload_contract",
                                         help="Договор с указанием срока и общей суммы")
    with col3:
        act_files = st.file_uploader("Акты выполненных работ (.xlsx)", type=["xlsx"], accept_multiple_files=True, key="upload_acts",
                                     help="Один или несколько актов выполненных работ (обязательно)")

    if st.button("Сверить", type="primary"):
        chosen = [*vor_files, *estimate_files, *([contract_file] if contract_file else []), *act_files]
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
            run_uploaded(chosen)

    sets_block()

    if "upload_results" in st.session_state:
        show_result(st.session_state["upload_results"], st.session_state["upload_summary"], st.session_state.get("upload_live", False))
    blocks.footer()
