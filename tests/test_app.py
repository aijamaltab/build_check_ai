"""app.py и страницы через streamlit.testing (без браузера): демо в режиме llm из реального кэша, без ключа и API."""
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
    """Весь HTML страницы одной строкой (карточки, метрики, светофор)."""
    return "\n".join(m.value for m in at.markdown)


def body(at) -> str:
    return page(at).split("</style>", 1)[-1]


def run_app() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=180).run()


def rationale_app():
    import os
    os.environ.setdefault("LLM_CACHE_ONLY", "1")
    from ui.screens import rationale
    rationale.render()


# ---------- страница «Программа» ----------
def test_program_page_is_a_product_showcase_with_live_demo(llm_env):
    at = run_app()
    assert not at.exception
    html = body(at)
    assert "Находит расхождения между ВОР, сметой, договором и актами" in html and "Демо на синтетических данных" in html
    assert "ИИ читает и сопоставляет названия, код считает и проверяет числа" in html
    for text in ("Четыре документа в одной таблице", "У каждого расхождения есть источник", "Оценка влияния на бюджет",
                 "Исходные файлы", "Результат сверки: капремонт школы"):
        assert text in html
    assert "Как это работает" not in html and "Читаем Excel" not in html                   # объяснение процесса живёт на странице обоснования
    assert html.index("Исходные файлы") < html.index("Результат сверки")                   # сначала файлы, потом итог по ним
    assert 'class="banner"' not in html
    assert html.count('class="issue-card"') == 13
    for text in ("Позиций проверено", "Возможных расхождений", "Возможное влияние на бюджет, сом", "Позиции с отклонением от плана",
                 "красные и жёлтые позиции: расхождение или выполнение меньше плана", "1 378 030", "Оценка размера возможных расхождений, не вывод о потерях"):
        assert text in html
    for label in ("Красные: 11 позиций", "Жёлтые: 7 позиций", "Зелёные: 30 позиций"):
        assert label in html
    assert "Прототип. Данные синтетические. Результат требует проверки специалистом." in html
    assert "Без ИИ и с ИИ" not in html                                        # сравнение режимов живёт на странице обоснования
    assert len(at.dataframe) == 2                                             # просмотр файла и таблица позиций; расхождения карточками


def test_cards_show_vor_and_act_side_by_side_as_written(llm_env):
    html = body(run_app())
    assert html.count('class="sides"') == 13
    assert "В ВОР" in html and "В актах" in html and "В смете" in html and "Договор" in html
    assert "«Арматура А500 d12»" in html and "«Арм. А500 Ø12»" in html                # как написано в ВОР и в акте
    assert "Всего 11,4 т" in html and "9,5 т" in html
    assert "Названия записаны по-разному в разных документах" in html
    assert "такой позиции не найдено" in html and "срок выполнения работ" in html.lower()
    assert "Что сделал ИИ" in html and "ИИ помог сопоставить" in html and "ИИ просмотрел весь список ВОР и не нашёл пару" in html


def test_table_view_uses_dataframe_instead_of_cards(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["view"] = "Таблица"
    at.run()
    assert not at.exception
    assert 'class="issue-card"' not in body(at)
    table = next(d.value for d in at.dataframe if "Влияние, сом" in d.value.columns)
    assert len(table) == 13 and {"Важность", "Тип", "Работа", "Что не так", "Влияние, сом", "Источник"} <= set(table.columns)


def test_filters_narrow_the_list(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["severity"] = "Низкая"
    at.run()
    assert not at.exception and 'class="issue-card"' not in body(at)
    assert any("По выбранным фильтрам расхождений нет." in i.value for i in at.info)


def test_file_viewer_shows_structure_and_sheet_as_in_excel(llm_env):
    at = run_app()
    html = body(at)
    assert at.selectbox[0].options[0] == "ВОР, каркас А · vor_1.xlsx" and len(at.selectbox[0].options) == 9
    assert "vor_1.xlsx" in html and "Ведомость объёмов работ (ВОР)" in html and "шаблон: ВОР, каркас А" in html
    assert "Позиций прочитано: <b>30</b>" in html and "Не распознано: <b>0</b>" in html
    assert "Колонки, которые распознаёт программа" in html and "Наименование работ и затрат" in html
    preview = at.dataframe[0].value
    assert list(preview.columns)[:3] == ["Строка", "A", "B"] and "ВЕДОМОСТЬ ОБЪЁМОВ РАБОТ" in " ".join(preview["A"].astype(str))


def test_file_viewer_switches_to_another_file(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=180)
    at.session_state["file_choice"] = "Договор · contract.xlsx"
    at.run()
    assert not at.exception
    html = body(at)
    assert "contract.xlsx" in html and "Подписи строк, которые распознаёт программа" in html and "Срок выполнения работ до" in html
    preview = at.dataframe[0].value
    assert "30.09.2025" in " ".join(preview["B"].astype(str)) and "13 954 000" in " ".join(preview["B"].astype(str))


# ---------- страница «Обоснование» ----------
def test_rationale_page_compares_modes_and_shows_ai_work(llm_env):
    at = AppTest.from_function(rationale_app, default_timeout=180).run()
    assert not at.exception
    html = body(at)
    for text in ("Зачем здесь ИИ", "Как это работает", "Читаем Excel", "Сопоставляем позиции", "Считаем и показываем",
                 "Светофор по позициям в двух режимах", "Строк без пары", "12 / 25 / 16", "11 / 7 / 30", "366 600 (и ещё 1 086 110 низкой уверенности)",
                 "Позиции с отклонением от плана (красные и жёлтые)", "Без ИИ и с ИИ", "Без ИИ (только правила)", "8 из 12", "12 из 12", "44,4%", "92,3%",
                 "Синтетические данные, оценка ориентировочная.", "Что показывает каждый режим", "Что сопоставил ИИ",
                 "Как ИИ и код делят работу", "Где ИИ ошибается", "Разборка пола"):
        assert text in html
    assert html.count('class="traffic"') == 2
    assert html.count('class="ex-card"') == 6 and "ИИ решил" in html and "Код проверил" in html
    assert "Без ИИ найдено 8 из 12 заложенных расхождений и 10 ложных. С ИИ найдено 12 из 12 и 1 ложное" in html
    assert [t.label for t in at.tabs] == ["Без ИИ (18)", "С ИИ (13)"]
    without_ai, with_ai, pairs = (d.value for d in at.dataframe)
    assert len(without_ai) == 18 and (without_ai["По эталону"].str.startswith("ложное")).sum() == 10
    assert len(with_ai) == 13 and (with_ai["По эталону"].str.startswith("ложное")).sum() == 1
    assert {"Как написано в документе", "Как написано в ВОР", "Уверенность", "Причина (ответ ИИ)"} <= set(pairs.columns) and len(pairs) >= 20
