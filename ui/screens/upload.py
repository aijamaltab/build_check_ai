"""Страница «Загрузка данных» (по умолчанию): свои файлы и готовые демо-наборы. Сверка идёт в отдельной папке сессии,
результат лежит в st.session_state["run_result"], затем переход на «Результаты»."""
import streamlit as st

from ui import components as ui
from ui import runner
from ui.live_ai import MAX_FILE_MB, MAX_FILES, PRIVACY_WARNING, get_api_key, scrub
from ui.llm_budget import session_budget, site_budget
from ui.screens import blocks
from ui.sets import SETS, zip_bytes

HERO_TITLE = "Сверка строительных документов"
HERO_LEAD = ("Сервис сопоставляет плановую ведомость, смету, договор и акты и показывает возможные расхождения: где смотреть и сколько это в сомах. "
             "Попробуйте на готовом примере или загрузите свои файлы.")
STEPS = [("1. Выберите данные", "Нажмите на готовый демо-набор или загрузите свои Excel-файлы."),
         ("2. Система сверяет", "ИИ понимает, что разные записи называют одну работу, а код считает объёмы и цены."),
         ("3. Смотрите результат", "Список возможных расхождений: файл, лист, строка и влияние в сомах.")]
GLOSSARY = ("ВОР (ведомость объёмов работ): план, какие работы и в каком объёме. Акт: что и сколько реально сделано. "
            "Смета: цены. Договор: срок и сумма.")
BASE_HINT = "  " + chr(10) + "Рекомендуем начать с него"
FIRST_TIME = ("Впервые здесь? Нажмите «Посмотреть результат» у базового демо-набора ниже: ответы ИИ уже сохранены, ключ не нужен, "
              "результат появится через несколько секунд. Данные синтетические.")
OFFLINE_INFO = ("Живой ИИ на этом сайте сейчас выключен: используются только сохранённые ответы. "
                "Для незнакомых названий работ ответов нет, такие позиции могут быть сопоставлены неверно и требуют проверки.")
NOT_RECOGNIZED = ("Загруженные файлы не были распознаны. Убедитесь, что они сохранены в формате .xlsx и содержат строки заголовков "
                  "с наименованием, единицей измерения и количеством.")


@st.cache_data(show_spinner=False)
def cached_zip(name: str) -> bytes:
    return zip_bytes(name)


def api_key() -> str | None:
    try:
        secrets = st.secrets
    except Exception:  # noqa: BLE001
        secrets = None
    return get_api_key(secrets)


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


def go_results(results_page) -> None:
    """Переход на «Результаты»; без навигации (страница запущена отдельно, например в тесте) просто обновляет страницу."""
    if results_page is not None:
        st.switch_page(results_page)
    st.rerun()


def run_with_progress(label: str, results_page, *, files=None, set_name=None) -> None:
    """Сверка с настоящим прогрессом (счётчики приходят из судей). Успех: переход на «Результаты»; ошибка или нераспознанные файлы: сообщение здесь."""
    key = api_key() if files is not None else None          # ключ только для своих файлов; демо-наборы идут из кэша
    bar = st.progress(0.0, text="Читаем файлы и сопоставляем названия…")
    status = st.empty()
    names = {"pairs": "пар названий", "rows": "строк без пары"}

    def progress(stage, done, total):
        bar.progress(min(1.0, done / total) if total else 1.0, text=f"Разобрано {done} из {total} {names[stage]}")
        status.markdown(f"Разобрано {done} из {total} {names[stage]}")

    run = None
    try:
        if files is not None:
            run = runner.execute(None, label, files=files, key=key, session=session_budget(), site=site_budget(), progress=progress)
        else:
            run = runner.execute_set(set_name, label, progress=progress)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось выполнить сверку документов: {scrub(exc, key)}. Проверьте формат файлов и структуру таблиц.")
    finally:
        bar.empty()
        status.empty()
    if run is None:
        return
    if not runner.recognised(run):
        errors = run["summary"].get("documents_with_errors") or []
        st.error(NOT_RECOGNIZED)
        if errors:
            st.warning(f"Файлы с ошибками при чтении: {', '.join(errors)}")
        return
    go_results(results_page)


def demo_block(results_page) -> None:
    ui.render(ui.section_html("Попробуйте на демо-наборе"))
    for name, title in SETS.items():
        with st.container(key=f"demo_{name}"):
            c1, c2, c3 = st.columns([3, 2, 2])
            c1.markdown(f"**{title}**" + (BASE_HINT if name == "base" else ""))
            c2.download_button("Скачать набор (zip)", cached_zip(name), file_name=f"{name}.zip", mime="application/zip", key=f"zip_{name}")
            if c3.button("Посмотреть результат", key=f"run_{name}", type="primary" if name == "base" else "secondary"):
                run_with_progress(title, results_page, set_name=name)


def render(results_page=None) -> None:
    ui.render(ui.hero_html(HERO_TITLE, HERO_LEAD))
    ui.render(ui.trio_html(STEPS))
    ui.render(f'<div class="note-small">{ui.escape(GLOSSARY)}</div>')
    st.success(FIRST_TIME)
    demo_block(results_page)

    ui.render(ui.section_html("Или загрузите свои файлы", "Нужны ВОР и хотя бы один акт; смета и договор необязательны."))
    live = bool(api_key())
    if live:
        st.warning(PRIVACY_WARNING)
    else:
        st.info(OFFLINE_INFO)

    with st.expander("Как подготовить файлы", expanded=False):
        st.write(f"""
        1. **ВОР (ведомость объёмов работ):** обязательно, один или несколько файлов.
        2. **Акты выполненных работ:** обязательно, один или несколько файлов.
        3. **Смета:** необязательно, один или несколько файлов, нужна для сверки цен за единицу.
        4. **Договор:** необязательно, нужен для проверки срока выполнения работ.
        5. **Формат и размер:** только Excel (.xlsx), не больше {MAX_FILE_MB} МБ на файл, не больше {MAX_FILES} файлов за один раз.
        """)

    st.caption(f"Только .xlsx, не больше {MAX_FILE_MB} МБ на файл, не больше {MAX_FILES} файлов.")
    col1, col2 = st.columns(2)
    with col1:
        vor_files = st.file_uploader("ВОР (.xlsx)", type=["xlsx"], accept_multiple_files=True, key="upload_vor",
                                     help="Один или несколько файлов ведомости объёмов работ (обязательно)")
        act_files = st.file_uploader("Акты выполненных работ (.xlsx)", type=["xlsx"], accept_multiple_files=True, key="upload_acts",
                                     help="Один или несколько актов выполненных работ (обязательно)")
    with col2:
        estimate_files = st.file_uploader("Смета (.xlsx, необязательно)", type=["xlsx"], accept_multiple_files=True, key="upload_estimate",
                                          help="Один или несколько файлов сметы в текущих ценах")
        contract_file = st.file_uploader("Договор (.xlsx, необязательно)", type=["xlsx"], key="upload_contract",
                                         help="Договор с указанием срока и общей суммы")

    if st.button("Сверить", type="primary", key="upload_run"):
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
            run_with_progress("загруженные файлы", results_page, files=[(f.name, bytes(f.getbuffer())) for f in chosen])

    blocks.footer()
