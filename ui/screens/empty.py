"""Состояние «результата ещё нет»: одно сообщение для страниц «Результаты» и «Исходные таблицы»."""
import streamlit as st

from ui import runner
from ui.sets import SETS

MESSAGE = "Загрузите данные: результата сверки пока нет."
DEMO_ERROR = "Не удалось собрать результат из демо-набора. Обновите страницу; если ошибка повторяется, сообщите разработчикам."


def empty_state(upload_page=None, key: str = "empty") -> None:
    """Сообщение, ссылка на страницу загрузки и кнопка «Запустить на демо-данных» (базовый набор из кэша ИИ; после неё страница обновляется)."""
    st.info(MESSAGE)
    if upload_page is not None:
        st.page_link(upload_page, label="Перейти к загрузке данных")
    if st.button("Запустить на демо-данных", type="primary", key=f"{key}_demo"):
        try:
            with st.spinner("Сверяем демо-набор…"):
                runner.execute_set("base", SETS["base"])
        except Exception:  # noqa: BLE001: пользователю человеческая ошибка, подробности в логе Streamlit
            st.error(DEMO_ERROR)
            return
        st.rerun()
