import os

os.environ.setdefault("LLM_CACHE_ONLY", "1")

import streamlit as st  # noqa: E402

from ui.screens import demo, rationale, results, upload  # noqa: E402
from ui.styles import inject  # noqa: E402

st.set_page_config(page_title="Сверка строительных документов", layout="wide", initial_sidebar_state="collapsed")
inject()

# страницы ссылаются друг на друга, поэтому сначала создаются все st.Page, обёртки берут их из замыкания
pages = {}


def demo_view() -> None:
    demo.render(pages["upload"], pages["results"])


def upload_view() -> None:
    upload.render(pages["results"])


pages["demo"] = st.Page(demo_view, title="Демо", url_path="demo", default=True)
pages["upload"] = st.Page(upload_view, title="Проверить свои файлы", url_path="upload")
pages["results"] = st.Page(results.render, title="Все результаты", url_path="results")
pages["rationale"] = st.Page(rationale.render, title="Как работает ИИ", url_path="rationale")
menu = list(pages.values())
try:
    navigation = st.navigation(menu, position="top")        # верхнее меню, если версия Streamlit умеет
except TypeError:
    navigation = st.navigation(menu)
navigation.run()
