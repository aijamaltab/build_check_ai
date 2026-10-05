"""Тесты страницы «Позиции» (ui/screens/positions.py) через AppTest."""
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.cache_guard import REAL_CACHE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def llm_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def positions_app():
    import os
    os.environ.setdefault("LLM_CACHE_ONLY", "1")
    from ui.screens import positions
    positions.render()


def test_positions_page_initial_render(llm_env):
    at = AppTest.from_function(positions_app, default_timeout=60).run()
    assert not at.exception
    html = "\n".join(m.value for m in at.markdown)
    assert "Позиции ведомости и выполнение" in html
    assert "Светофор позиций" in html
    assert "Светофор по позициям" in html
    assert "Красные: 11 позиций" in html
    assert "Жёлтые: 7 позиций" in html
    assert "Зелёные: 30 позиций" in html

    # Должна быть показана таблица позиций
    assert len(at.dataframe) >= 1
    table = at.dataframe[0].value
    assert len(table) == 48  # 11 + 7 + 30 = 48 позиций
    assert {"Работа", "Ед.", "План", "Факт", "Выполнено, %", "Статус"} <= set(table.columns)


def test_positions_search_filter(llm_env):
    at = AppTest.from_function(positions_app, default_timeout=60)
    at.session_state["positions_query"] = "арматура"
    at.run()
    assert not at.exception
    table = at.dataframe[0].value
    assert len(table) < 48
    assert len(table) > 0
    for name in table["Работа"]:
        assert "арм" in name.lower()


def test_positions_only_review_filter(llm_env):
    at = AppTest.from_function(positions_app, default_timeout=60)
    at.session_state["positions_only_review"] = True
    at.run()
    assert not at.exception
    table = at.dataframe[0].value
    # 11 красных + 7 жёлтых = 18 позиций для проверки
    assert len(table) == 18
    statuses = set(table["Статус"])
    assert "Зелёный" not in statuses
    assert {"Красный", "Жёлтый"} == statuses


def test_positions_color_filter(llm_env):
    at = AppTest.from_function(positions_app, default_timeout=60)
    at.session_state["positions_colors"] = ["Зелёные"]
    at.run()
    assert not at.exception
    table = at.dataframe[0].value
    assert len(table) == 30  # 30 зелёных
    assert set(table["Статус"]) == {"Зелёный"}


def test_positions_unit_filter(llm_env):
    at = AppTest.from_function(positions_app, default_timeout=60)
    at.session_state["positions_units"] = ["м3"]
    at.run()
    assert not at.exception
    table = at.dataframe[0].value
    assert len(table) > 0
    assert set(table["Ед."]) == {"м3"}


def test_positions_empty_result_message(llm_env):
    at = AppTest.from_function(positions_app, default_timeout=60)
    at.session_state["positions_query"] = "несуществующая работа 12345"
    at.run()
    assert not at.exception
    assert len(at.info) >= 1
    assert "не найдено" in at.info[0].value
