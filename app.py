import os

os.environ.setdefault("LLM_CACHE_ONLY", "1")

import streamlit as st  # noqa: E402

from ui import components as ui  # noqa: E402
from ui import runner, sheets_view  # noqa: E402
from ui.screens import rationale, results, upload  # noqa: E402
from ui.styles import inject  # noqa: E402

st.set_page_config(page_title="Сверка строительных документов", layout="wide", initial_sidebar_state="collapsed")
inject()

# страницы ссылаются друг на друга, поэтому сначала создаются все st.Page, обёртки берут их из замыкания
pages = {}


def upload_view() -> None:
    upload.render(pages["results"])


def results_view() -> None:
    results.render(pages["upload"], pages["rationale"])


def sheets_page_view() -> None:
    sheets_view.render(pages["upload"])


pages["upload"] = st.Page(upload_view, title="Загрузка данных", url_path="upload", default=True)
pages["results"] = st.Page(results_view, title="Результаты", url_path="results")
pages["sheets"] = st.Page(sheets_page_view, title="Исходные таблицы", url_path="sheets")
pages["rationale"] = st.Page(rationale.render, title="Как работает ИИ", url_path="rationale")


def topbar() -> None:
    """Узкая шапка над страницей: проект и режим (до первой сверки: «данные не загружены»)."""
    run = runner.current_run()
    if run is None:
        ui.render(ui.topbar_html("данные не загружены"))
        return
    ui.render(ui.topbar_html(run["label"], mode=runner.mode_label(run)))


topbar()
navigation = st.navigation(list(pages.values()), position="sidebar")
navigation.run()
