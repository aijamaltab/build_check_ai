"""Просмотрщик исходных файлов демо-проекта: структура файла и сам лист как в Excel."""
from pathlib import Path

import streamlit as st

from src.config import load_config
from ui import components as ui
from ui.data import describe_file, file_label, file_preview
from ui.loader import DEMO_DIR


def render_files(results: dict) -> None:
    ui.render(ui.section_html("Исходные файлы", "Девять Excel-файлов демо-проекта: ВОР, смета, договор и акты. Выберите файл, чтобы увидеть, "
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
