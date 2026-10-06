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


# ---------- страница «Главная» ----------
START = "Загрузить файлы в систему и сверить"


def home_started() -> AppTest:
    at = run_app()
    next(b for b in at.button if b.label == START).click().run()
    return at



def test_home_before_click_shows_intro_and_files_but_no_result(llm_env):
    at = run_app()
    assert not at.exception
    html = body(at)
    assert "Сверка строительных документов" in html and "Сопоставляет ВОР, смету, договор и акты" in html
    for text in ("Приводит четыре документа к одной таблице", "ИИ сопоставляет названия, код считает объёмы и цены",
                 "Показывает возможные расхождения и их влияние на бюджет в сомах",
                 "ВОР: ведомость объёмов работ, список работ и их объёмов по проекту", "Демо-проект: файлы", "Данные демо синтетические"):
        assert text in html
    assert "trio-num" not in html and html.count('class="step"') == 3
    assert len(at.download_button) == 9 and any(b.label == START for b in at.button)       # девять файлов и главная кнопка
    for hidden in ('class="tile"', 'class="tbar"', "Итоги сверки", "Возможные расхождения"):
        assert hidden not in html                                                       # до нажатия результата нет
    assert len(at.get("iframe")) == 0
    assert "Прототип. Данные синтетические. Результат требует проверки специалистом." in html


def test_home_file_table_lists_nine_files_with_roles_and_row_counts(llm_env):
    at = run_app()
    text = " ".join(m.value for m in at.markdown)
    for name in ("vor_1.xlsx", "vor_2.xlsx", "estimate.xlsx", "contract.xlsx", "act_1.xlsx", "act_5.xlsx"):
        assert name in text
    assert sorted(d.label for d in at.download_button) == ["Скачать"] * 9


def test_home_after_click_shows_tiles_traffic_issue_table_and_summary(llm_env):
    at = home_started()
    assert not at.exception
    html = body(at)
    assert "Результат собран из сохранённых ответов ИИ" in html and "ключ" not in html.lower()      # про ключ только на странице загрузки
    assert html.count('class="tile"') == 5
    for label in ("Строк в документах", "Позиций ВОР", "Расхождений", "Возможное влияние, сом", "Позиций с отклонением от плана"):
        assert label in html
    assert ">180<" in html and ">48<" in html and ">13<" in html and "1 378 030" in html and ">18<" in html
    assert html.count('class="tbar"') == 1 and html.count('class="legend"') == 1                  # светофор и пояснение один раз
    assert "Красные: <b>11</b>" in html and "Жёлтые: <b>7</b>" in html and "Зелёные: <b>30</b>" in html
    assert 'class="issue-card"' not in html and len(at.get("iframe")) == 1
    assert "Итоги сверки" in html and html.count("<li>") == 5
    assert "Найдено 13 возможных расхождений" in html and "Без ИИ было бы 18 расхождений, из них 10 ложных; с ИИ 13, из них ложных 1." in html
    assert "Проверить первыми: Монтаж системы видеонаблюдения (240 000 сом)" in html
    assert any(b.label == "Начать заново" for b in at.button)


def test_home_reset_returns_to_files_view(llm_env):
    at = home_started()
    next(b for b in at.button if b.label == "Начать заново").click().run()
    assert not at.exception and 'class="tile"' not in body(at) and any(b.label == START for b in at.button)


def test_topbar_shows_project_run_date_and_mode(llm_env):
    html = page(run_app())
    assert "Проект:" in html and "Капремонт школы" in html and "Прогон:" in html and "Режим:" in html and "С ИИ (из кэша)" in html


# ---------- страница «Сверочная ведомость» ----------
def test_ledger_page_has_table_component_and_report_tab(llm_env):
    at = results_run()
    assert not at.exception
    assert [t.label for t in at.tabs][:2] == ["Ведомость", "Отчёт"]
    html = body(at)
    assert "Сверочная ведомость" in html
    assert "Возможное влияние на бюджет, сом" not in html and "Строк в документах" not in html     # метрики здесь не повторяются
    assert 'class="issue-card"' not in html and len(at.get("iframe")) == 1                           # таблица это компонент
    assert len(at.download_button) == 1


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
    assert 'class="ex-card"' not in html and html.count('class="role"') == 3
    for text in ("читает и сопоставляет названия", "считает объёмы и цены, применяет допуск 5 %", "ответ ИИ принимается, только если совпали единица измерения, вид работ, числа и уверенность не ниже порога"):
        assert text in html
    assert "<th>Название в ВОР</th>" in html and "<th>Итог</th>" in html and html.count('class="chain"') == 1
    assert html.count("✓ принято") + html.count("✕ отклонено") == 6
    assert "ИИ ошибается реже, чем помогает, но ошибки бывают. Мы показываем их открыто" in html
    assert "Что мы меняем:" in html and "будут помечаться как требующие проверки, а не как уверенное расхождение" in html and "ещё не сделано" in html
    assert html.count('class="err-card"') == 3 and html.count('class="err-tag">набор 3') == 2 and html.count('class="err-tag">набор 2') == 1
    for text in ("Устройство перекрытий из бетона В25", "Плиты перекрытий монолитные М350", "Снятие шифера с крыши", "LED-панели светильники монтаж",
                 "уверенность 0,85", "уверенность 0,90", "Как поймает человек"):
        assert text in html
    assert 'class="errbox"' not in html
    assert "Без ИИ найдено 8 из 12 заложенных расхождений и 10 ложных. С ИИ найдено 12 из 12 и 1 ложное" in html
    assert [t.label for t in at.tabs] == ["Без ИИ (18)", "С ИИ (13)"]
    assert html.count('class="plain"') == 3 and html.count('class="row-false"') == 11             # таблицы с переносом текста; ложные: 10 без ИИ и 1 с ИИ
    for head in ("Как написано в документе", "Как написано в ВОР", "Уверенность", "Причина (ответ ИИ)", "По эталону"):
        assert f"<th>{head}</th>" in html
    assert html.count("<tr") > 50


def test_rationale_page_has_collapsed_source_files_viewer(llm_env):
    at = AppTest.from_function(rationale_app, default_timeout=180).run()
    assert not at.exception
    assert [e.label for e in at.expander] == ["Исходные файлы демо"] and at.expander[0].proto.expanded is False
    assert at.selectbox[0].options[0] == "ВОР, каркас А · vor_1.xlsx" and len(at.selectbox[0].options) == 9
    html = body(at)
    assert "Ведомость объёмов работ (ВОР)" in html and "Колонки, которые распознаёт программа" in html
    assert html.index("Где ИИ ошибается") < html.index("Исходные файлы")                 # просмотрщик в самом низу
    assert list(at.dataframe[0].value.columns)[:3] == ["Строка", "A", "B"]


def test_app_registers_four_pages_in_new_order():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    titles = ["Главная", "Проверить свои файлы", "Сверочная ведомость", "Как работает ИИ"]
    positions = [source.index(f'title="{t}"') for t in titles]
    assert positions == sorted(positions)
    assert all(f'url_path="{p}"' in source for p in ("home", "upload", "ledger", "rationale"))
    assert 'position="sidebar"' in source                                    # навигация слева
