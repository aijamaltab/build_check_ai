import os

os.environ.setdefault("LLM_CACHE_ONLY", "1")

import streamlit as st  # noqa: E402

from ui.screens import positions, product, rationale, upload  # noqa: E402
from ui.styles import inject  # noqa: E402

st.set_page_config(page_title="Сверка строительных документов", layout="wide", initial_sidebar_state="collapsed")
inject()

rationale_page = st.Page(rationale.render, title="Обоснование: с ИИ и без ИИ", url_path="rationale")
upload_page = st.Page(upload.render, title="Загрузить свои файлы", url_path="upload")
positions_page = st.Page(positions.render, title="Позиции", url_path="positions")


def program() -> None:
    product.render(rationale_page)


program_page = st.Page(program, title="Программа", url_path="program", default=True)
pages = [program_page, upload_page, positions_page, rationale_page]
try:
    navigation = st.navigation(pages, position="top")        # верхнее меню, если версия Streamlit умеет
except TypeError:
    navigation = st.navigation(pages)
navigation.run()
