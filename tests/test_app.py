"""app.py целиком через streamlit.testing (без браузера): демо в режиме llm из реального кэша, без ключа и API."""
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.cache_guard import REAL_CACHE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def llm_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))        # реальный кэш, только чтение
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))     # базы приложения во временной папке теста


def page(at) -> str:
    """Весь HTML экрана одной строкой (карточки, метрики, светофор)."""
    return "\n".join(m.value for m in at.markdown)


def test_default_screen_is_llm_mode_with_13_cards_and_no_banner(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()
    assert not at.exception
    html = page(at)
    assert "Сверка строительных документов" in html and "ВОР · смета · договор · акты в одной таблице" in html
    assert "Демо на синтетических данных" in html and "Режим: С ИИ (ответы Gemini из кэша)" in html
    assert 'class="banner"' not in html
    assert html.count('class="issue-card"') == 13
    for text in ("Позиций проверено", "Возможных расхождений", "Возможное влияние на бюджет, сом", "Нужно проверить вручную",
                 "1 378 030", "Оценка размера возможных расхождений, не вывод о потерях"):
        assert text in html
    for label in ("Красные: 11 позиций", "Жёлтые: 7 позиций", "Зелёные: 30 позиций"):
        assert label in html
    assert "ИИ помог сопоставить" in html and "В актах 11,4 т при 9,5 т в ВОР (+20,0%)" in html
    assert "ИИ читает и сопоставляет названия, обычный код считает и проверяет числа." in html
    assert "Прототип. Данные синтетические. Результат требует проверки специалистом." in html
    assert len(at.dataframe) == 1                                             # таблица позиций; расхождения карточками


def test_switch_to_without_ai_shows_rules_only_numbers(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["mode"] = "Без ИИ"
    at.run()
    assert not at.exception
    html = page(at)
    assert "Режим: Без ИИ (только правила)" in html
    assert "ИИ выключен: похожие названия не склеиваются, ложных расхождений больше" in html
    assert html.count('class="issue-card"') == 18 and "366 600" in html and "1 086 110" in html
    assert "Красные: 12 позиций" in html and "Жёлтые: 25 позиций" in html and "Зелёные: 16 позиций" in html
    assert "Низкая уверенность, требует проверки" in html and "ИИ помог сопоставить" not in html


def test_table_view_uses_dataframe_instead_of_cards(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["view"] = "Таблица"
    at.run()
    assert not at.exception
    assert 'class="issue-card"' not in page(at)
    table = at.dataframe[0].value
    assert len(table) == 13 and {"Важность", "Тип", "Работа", "Что не так", "Влияние, сом", "Источник"} <= set(table.columns)


def test_filters_narrow_the_list(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["severity"] = "Низкая"
    at.run()
    assert not at.exception and 'class="issue-card"' not in page(at)
    assert any("По выбранным фильтрам расхождений нет." in i.value for i in at.info)
