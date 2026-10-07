"""Счётчики живых запросов ИИ для страницы загрузки: на сессию (в session_state) и на весь сайт в сутки (один на процесс)."""
import streamlit as st

from src.llm.budget import CallBudget
from ui.live_ai import SESSION_LIMIT, SITE_DAILY_LIMIT


@st.cache_resource
def site_budget() -> CallBudget:
    """Общий суточный счётчик живых запросов: один на процесс, то есть на всех посетителей."""
    return CallBudget(SITE_DAILY_LIMIT, daily=True)


def session_budget() -> CallBudget:
    if "live_budget" not in st.session_state:               # в session_state только счётчик, ключа там нет
        st.session_state["live_budget"] = CallBudget(SESSION_LIMIT)
    return st.session_state["live_budget"]
