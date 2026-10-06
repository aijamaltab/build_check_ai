import os

os.environ.setdefault("LLM_CACHE_ONLY", "1")

import streamlit as st  # noqa: E402

from ui import components as ui  # noqa: E402
from ui.data import fmt_run_at  # noqa: E402
from ui.loader import build_demo  # noqa: E402
from ui.screens import demo, rationale, results, upload  # noqa: E402
from ui.styles import inject  # noqa: E402

st.set_page_config(page_title="Сверка строительных документов", layout="wide", initial_sidebar_state="collapsed")
inject()

# страницы ссылаются друг на друга, поэтому сначала создаются все st.Page, обёртки берут их из замыкания
pages = {}


def demo_view() -> None:
    demo.render(pages["upload"], pages["results"])


pages["demo"] = st.Page(demo_view, title="Демо", url_path="demo", default=True)
pages["upload"] = st.Page(upload.render, title="Проверить свои файлы", url_path="upload")
pages["results"] = st.Page(results.render, title="Сверочная ведомость", url_path="ledger")
pages["rationale"] = st.Page(rationale.render, title="Как работает ИИ", url_path="rationale")


def topbar() -> None:
    """Узкая шапка над страницей: проект, дата прогона, режим."""
    try:
        summary = build_demo("llm")["summary"]
        run_at = build_demo("llm")["run_at"]
    except Exception:  # noqa: BLE001: без шапки страница всё равно покажет свою ошибку
        return
    mode = "С ИИ (из кэша)" if summary.get("mode") == "llm" else "Без ИИ (базовый режим)"
    ui.render(ui.topbar_html("Капремонт школы (демо, синтетические данные)", fmt_run_at(run_at), mode))


topbar()
navigation = st.navigation(list(pages.values()), position="sidebar")
navigation.run()
