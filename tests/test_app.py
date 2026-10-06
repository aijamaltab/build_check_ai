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


def results_app():
    import os
    os.environ.setdefault("LLM_CACHE_ONLY", "1")
    from ui.screens import results
    results.render()


def results_run() -> AppTest:
    return AppTest.from_function(results_app, default_timeout=180).run()


# ---------- страница «Демо» ----------
def test_demo_page_shows_summary_and_top_issues(llm_env):
    at = run_app()
    assert not at.exception
    html = body(at)
    assert "Находит расхождения между ВОР, сметой, договором и актами" in html and "Демо на синтетических данных" in html
    assert "ИИ читает и сопоставляет названия, код считает и проверяет числа" in html
    assert 'class="banner"' not in html
    for text in ("Возможных расхождений", "Возможное влияние на бюджет, сом", "Позиции с отклонением от плана",
                 "красные и жёлтые позиции: расхождение или выполнение меньше плана", "1 378 030",
                 "Оценка размера возможных расхождений, не вывод о потерях"):
        assert html.count(text) == 1                                              # метрики один раз
    for label in ("Красные: 11 позиций", "Жёлтые: 7 позиций", "Зелёные: 30 позиций"):
        assert label in html
    assert html.count('class="issue-card"') == 5 and "Главные расхождения" in html
    assert html.count('class="legend"') == 1                                      # легенда один раз
    assert "Исходные файлы" not in html and len(at.dataframe) == 0                # просмотрщик файлов убран с главной
    assert "Прототип. Данные синтетические. Результат требует проверки специалистом." in html
    assert "Без ИИ и с ИИ" not in html


def test_demo_metric_labels_rows_and_traffic_positions_honestly(llm_env):
    html = body(run_app())
    assert "Строк в документах" in html and "ВОР, смета и акты, без договора" in html and ">180<" in html
    assert "Позиций ВОР в светофоре: 48" in html and "Позиций проверено" not in html


# ---------- страница «Все результаты» ----------
def test_results_page_has_three_tabs_and_no_metrics(llm_env):
    at = results_run()
    assert not at.exception
    assert [t.label for t in at.tabs][:3] == ["Расхождения", "Позиции", "Отчёт"]
    html = body(at)
    assert "Возможное влияние на бюджет, сом" not in html and "Строк в документах" not in html
    assert html.count('class="issue-card"') == 13 and html.count('class="sides"') == 13
    assert html.count('class="legend"') == 1
    assert len(at.download_button) == 1


def test_cards_show_vor_and_act_side_by_side_as_written(llm_env):
    html = body(results_run())
    assert "В ВОР" in html and "В актах" in html and "В смете" in html and "Договор" in html
    assert "«Арматура А500 d12»" in html and "«Арм. А500 Ø12»" in html                # как написано в ВОР и в акте
    assert "Всего 11,4 т" in html and "9,5 т" in html
    assert "Названия записаны по-разному в разных документах" in html
    assert "такой позиции не найдено" in html and "срок выполнения работ" in html.lower()
    assert "Что сделал ИИ" in html and "ИИ помог сопоставить" in html and "ИИ просмотрел весь список ВОР и не нашёл пару" in html


def test_table_view_uses_dataframe_instead_of_cards(llm_env):
    at = AppTest.from_function(results_app, default_timeout=180)
    at.session_state["view"] = "Таблица"
    at.run()
    assert not at.exception
    assert 'class="issue-card"' not in body(at)
    table = next(d.value for d in at.dataframe if "Влияние, сом" in d.value.columns)
    assert len(table) == 13 and {"Важность", "Тип", "Работа", "Что не так", "Влияние, сом", "Источник"} <= set(table.columns)


def test_filters_narrow_the_list(llm_env):
    at = AppTest.from_function(results_app, default_timeout=180)
    at.session_state["severity"] = "Низкая"
    at.run()
    assert not at.exception and 'class="issue-card"' not in body(at)
    assert any("По выбранным фильтрам расхождений нет." in i.value for i in at.info)


def test_results_positions_tab_has_all_positions(llm_env):
    at = results_run()
    assert any(len(d.value) == 48 and "Статус" in d.value.columns for d in at.dataframe)


# ---------- страница «Как работает ИИ» ----------
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
    without_ai, with_ai, pairs = (d.value for d in list(at.dataframe)[:3])
    assert len(without_ai) == 18 and (without_ai["По эталону"].str.startswith("ложное")).sum() == 10
    assert len(with_ai) == 13 and (with_ai["По эталону"].str.startswith("ложное")).sum() == 1
    assert {"Как написано в документе", "Как написано в ВОР", "Уверенность", "Причина (ответ ИИ)"} <= set(pairs.columns) and len(pairs) >= 20


def test_rationale_page_has_collapsed_source_files_viewer(llm_env):
    at = AppTest.from_function(rationale_app, default_timeout=180).run()
    assert not at.exception
    assert [e.label for e in at.expander] == ["Исходные файлы демо"] and at.expander[0].proto.expanded is False
    assert at.selectbox[0].options[0] == "ВОР, каркас А · vor_1.xlsx" and len(at.selectbox[0].options) == 9
    html = body(at)
    assert "Ведомость объёмов работ (ВОР)" in html and "Колонки, которые распознаёт программа" in html
    assert html.index("Где ИИ ошибается") < html.index("Исходные файлы")                 # просмотрщик в самом низу
    assert list(at.dataframe[-1].value.columns)[:3] == ["Строка", "A", "B"]


def test_app_registers_four_pages_in_new_order():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    titles = ["Демо", "Проверить свои файлы", "Все результаты", "Как работает ИИ"]
    positions = [source.index(f'title="{t}"') for t in titles]
    assert positions == sorted(positions)
    assert all(f'url_path="{p}"' in source for p in ("demo", "upload", "results", "rationale"))
