import os

os.environ.setdefault("LLM_CACHE_ONLY", "1")

import streamlit as st  # noqa: E402

from ui import components as ui  # noqa: E402
from ui import sheets_view  # noqa: E402
from ui.data import fmt_run_at  # noqa: E402
from ui.loader import build_demo  # noqa: E402
from ui.screens import home, rationale, results, upload  # noqa: E402
from ui.styles import inject  # noqa: E402

st.set_page_config(page_title="Сверка строительных документов", layout="wide", initial_sidebar_state="collapsed")
inject()

# страницы ссылаются друг на друга, поэтому сначала создаются все st.Page, обёртки берут их из замыкания
pages = {}


def home_view() -> None:
    home.render(pages["upload"], pages["results"], pages["rationale"])


pages["home"] = st.Page(home_view, title="Главная", url_path="home", default=True)
pages["upload"] = st.Page(upload.render, title="Проверить свои файлы", url_path="upload")
pages["results"] = st.Page(results.render, title="Сверочная ведомость", url_path="ledger")
pages["rationale"] = st.Page(rationale.render, title="Как работает ИИ", url_path="rationale")
pages["sheets"] = st.Page(sheets_view.render, title="Аудит документов (Sheets)", url_path="sheets")


def topbar() -> None:
    """Узкая шапка над страницей: проект, дата прогона, режим."""
    ui.render(ui.topbar_html("Капремонт школы (демо)"))


topbar()
navigation = st.navigation(list(pages.values()), position="sidebar")
navigation.run()
