"""app.py и страницы через streamlit.testing (без браузера): демо в режиме llm из реального кэша, без ключа и API."""
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.cache_guard import REAL_CACHE

ROOT = Path(__file__).resolve().parents[1]
START = "Запустить на демо-данных"
TITLES = ["Загрузка данных", "Результаты", "Исходные таблицы", "Как работает ИИ"]


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


def demo_started(key: str = "run_base") -> AppTest:
    """Полный поток через app.py: клик по демо-набору на странице загрузки -> switch_page -> «Результаты»."""
    at = run_app()
    at.button(key=key).click().run()
    return at


def cards(at) -> int:
    return body(at).count('class="issue-card"')


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


def sheets_app():
    import os
    os.environ.setdefault("LLM_CACHE_ONLY", "1")
    from ui import runner, sheets_view
    if runner.current_run() is None:
        runner.execute_set("base", "Базовый набор")
    sheets_view.render()


def results_with_run_app():
    """Страница «Результаты» с готовым прогоном: AppTest после switch_page перезапускает страницу по умолчанию, поэтому виджеты проверяем отдельно."""
    import os
    os.environ.setdefault("LLM_CACHE_ONLY", "1")
    from ui import runner
    from ui.screens import results
    if runner.current_run() is None:
        runner.execute_set("base", "Базовый набор")
    results.render()


def empty_sheets_app():
    from ui import sheets_view
    sheets_view.render()


# ---------- структура сайта ----------
def test_app_registers_four_pages_in_new_order():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    positions = [source.index(f'title="{t}"') for t in TITLES]
    assert positions == sorted(positions)
    assert all(f'url_path="{p}"' in source for p in ("upload", "results", "sheets", "rationale"))
    assert 'title="Загрузка данных", url_path="upload", default=True' in source                  # страница по умолчанию
    assert 'position="sidebar"' in source and "st.navigation" in source                           # навигация слева


# ---------- «Загрузка данных» ----------
def test_default_page_is_upload_with_uploaders_and_three_demo_sets(llm_env):
    at = run_app()
    assert not at.exception
    html = body(at)
    assert "Сверка строительных документов" in html and "Попробуйте на демо-наборе" in html and "Или загрузите свои файлы" in html and "Данные синтетические" in page(at)
    assert {u.key for u in at.file_uploader} == {"upload_vor", "upload_acts", "upload_estimate", "upload_contract"}
    assert [b.key for b in at.button] == ["run_base", "run_set_3", "run_set_4", "upload_run"]       # демо выше загрузки своих файлов
    assert [d.label for d in at.download_button] == ["Скачать набор (zip)"] * 3
    assert "Базовый набор" in html and "Набор 3" in html and "Набор 4" in html
    assert "Проект:</b> данные не загружены" in html and "Прогон:" not in html                    # шапка до первой сверки
    assert "run_result" not in at.session_state and not at.get("iframe")
    assert "Прототип. Данные синтетические. Результат требует проверки специалистом." in html


def test_demo_click_runs_check_and_switches_to_results(llm_env):
    at = demo_started()
    assert not at.exception and not at.error
    run = at.session_state["run_result"]
    assert run["summary"]["files"] == 9 and run["summary"]["z"] == 13 and run["set_name"] == "base" and run["summary"]["ai"]["calls"] == 0
    assert [t.label for t in at.tabs][:3] == ["Сводка", "Расхождения", "Позиции"]               # уже страница «Результаты»
    assert not at.file_uploader


@pytest.mark.parametrize("key,issues", [("run_base", 13), ("run_set_3", 15), ("run_set_4", 15)])
def test_each_demo_set_runs_from_cache_without_new_ai_calls(llm_env, key, issues):
    at = demo_started(key)
    assert not at.exception and not at.error
    summary = at.session_state["run_result"]["summary"]
    ai = summary["ai"]
    assert summary["files"] == 9 and summary["z"] == issues and summary["mode"] == "llm"
    assert ai["calls"] == 0 and ai["cache_hits"] > 0 and ai["errors"] == 0 and ai["no_answer"] == 0     # ответы ИИ только из кэша, пропусков нет
    assert ai["pairs_no_decision"] == 0 and ai["rows_no_decision"] == 0


def test_runs_of_different_sessions_use_separate_database_files(llm_env, tmp_path):
    first, second = demo_started(), demo_started("run_set_3")
    a, b = first.session_state["run_result"], second.session_state["run_result"]
    assert a["db_path"] != b["db_path"] and Path(a["db_path"]).exists() and Path(b["db_path"]).exists()   # один не затёр другой
    assert Path(a["db_path"]).is_relative_to(tmp_path) and ROOT not in Path(a["db_path"]).parents       # база не в репозитории
    assert a["summary"]["z"] == 13 and b["summary"]["z"] == 15


def test_new_run_in_the_same_session_removes_the_previous_workdir(llm_env, tmp_path):
    from ui import runner

    def two_runs():
        from ui import runner as r
        import streamlit as st
        r.execute_set("base", "Базовый набор")
        st.session_state["first_dir"] = st.session_state[r.RUN_KEY]["workdir"]
        r.execute_set("set_3", "Набор 3")

    at = AppTest.from_function(two_runs, default_timeout=180).run()
    assert not at.exception
    assert not Path(at.session_state["first_dir"]).exists() and Path(at.session_state[runner.RUN_KEY]["workdir"]).exists()
    assert len(list(tmp_path.glob("buildcheck_run_*"))) == 1


# ---------- «Результаты» ----------
def test_results_empty_state_offers_upload_and_demo(llm_env):
    at = AppTest.from_function(results_app, default_timeout=180).run()
    assert not at.exception
    assert any("Загрузите данные" in i.value for i in at.info) and not at.tabs
    assert [b.label for b in at.button] == [START] and not at.download_button


def test_results_empty_state_demo_button_builds_result_in_place(llm_env):
    at = AppTest.from_function(results_app, default_timeout=180).run()
    at.button(key="results_demo").click().run()
    assert not at.exception and not at.error
    assert [t.label for t in at.tabs] == ["Сводка", "Расхождения", "Позиции"] and at.session_state["run_result"]["summary"]["z"] == 13


def test_results_summary_tab_has_tiles_traffic_charts_and_totals(llm_env):
    at = demo_started()
    html = body(at)
    assert html.count('class="tile"') == 5
    for label in ("Строк в документах", "Позиций ВОР", "Расхождений", "Возможное влияние, сом", "Позиций с отклонением от плана"):
        assert label in html
    assert ">180<" in html and ">48<" in html and ">13<" in html and "1 378 030" in html and ">18<" in html
    assert html.count('class="tbar"') == 1 and html.count('class="legend"') == 1                  # светофор один раз
    assert "Красные: <b>11</b>" in html and "Жёлтые: <b>7</b>" in html and "Зелёные: <b>30</b>" in html
    assert len(at.get("vega_lite_chart")) == 2                                                # диаграммы: по типам и влияние
    assert "Итоги сверки" in html and html.count("<li>") == 5
    assert "Найдено 13 возможных расхождений" in html and "Без ИИ было бы 18 расхождений, из них 10 ложных; с ИИ 13, из них ложных 1." in html
    assert "Проверить первыми: Монтаж системы видеонаблюдения (240 000 сом)" in html
    assert "Результат собран из сохранённых ответов ИИ" in html and "ключ" not in html.lower()
    assert [d.label for d in at.download_button] == ["Скачать отчёт в Excel (.xlsx)"]


def test_results_have_no_duplicate_blocks(llm_env):
    html = body(demo_started())
    assert html.count("Итоги сверки") == 1 and html.count("Возможные расхождения") == 1 and html.count('class="tile"') == 5
    assert "Сверочная ведомость" not in html and "Главная" not in html


def test_results_issues_tab_shows_cards_with_sources_and_filters(llm_env):
    at = AppTest.from_function(results_with_run_app, default_timeout=180).run()
    assert at.button_group(key="issues_view").value == "Таблица" and cards(at) == 0         # по умолчанию таблица: её проще читать
    at.button_group(key="issues_view").set_value("Карточки").run()
    assert cards(at) == 13 and len(at.get("iframe")) == 1                                           # карточки; таблица позиций это компонент
    html = body(at)
    assert "Показано 13 из 13" in html and html.count("issue-src") >= 13
    at.selectbox(key="flt_severity").select("высокая").run()
    high = cards(at)
    assert 0 < high < 13 and f"Показано {high} из 13" in body(at)
    at.selectbox(key="flt_severity").select("Все").run()
    at.multiselect(key="flt_types").select("price_increase").run()
    assert 0 < cards(at) < 13
    at.text_input(key="flt_query").input("такой работы нет").run()
    assert cards(at) == 0 and any("нет" in i.value for i in at.info)


def test_results_issues_table_view_has_readable_columns_and_filters(llm_env):
    at = AppTest.from_function(results_with_run_app, default_timeout=180).run()
    assert not at.exception and [o for o in at.button_group(key="issues_view").options] == ["Таблица", "Карточки"]
    html = body(at)
    for head in ("Важность", "Тип", "Работа", "Что не так", "Влияние, сом", "Источник", "Пометка"):
        assert f"<th>{head}</th>" in html                                                       # понятные заголовки колонок
    assert html.count('data-label="Работа"') == 13 and "act_2.xlsx" in html and "None" not in html.split("</style>")[-1]
    at.selectbox(key="flt_severity").select("высокая").run()
    rows = body(at).count('data-label="Работа"')
    assert 0 < rows < 13 and f"Показано {rows} из 13" in body(at)
    at.text_input(key="flt_query").input("такой работы нет").run()
    assert 'data-label="Работа"' not in body(at) and any("нет" in i.value for i in at.info)


def test_results_positions_tab_has_ledger_component(llm_env):
    at = demo_started()
    assert len(at.get("iframe")) == 1 and "Позиции со светофором" in body(at)


def test_topbar_shows_project_run_date_and_mode_after_run(llm_env):
    html = page(demo_started())
    assert "Проект:" in html and "Базовый набор" in html and "Режим:" in html and "С ИИ (из кэша)" in html
    assert "Прогон:" not in html                                                         # дата прогона в шапке не показывается


# ---------- «Исходные таблицы» ----------
def test_sheets_empty_state_offers_upload_and_demo(llm_env):
    at = AppTest.from_function(empty_sheets_app, default_timeout=60).run()
    assert not at.exception and any("Загрузите данные" in i.value for i in at.info)
    assert [b.label for b in at.button] == [START] and not at.get("iframe")


def test_sheets_page_reads_run_result_and_numbers_come_from_the_run(llm_env):
    at = AppTest.from_function(sheets_app, default_timeout=180).run()
    assert not at.exception and len(at.get("iframe")) == 1
    model = at.session_state["run_result"]["sheets_model"]
    card = model["project"]
    assert card["issues"] == 13 and card["impact_som"] == "1 378 030 сом" and (card["red"], card["yellow"], card["green"]) == (11, 7, 30)
    assert len(model["tabs"]) == 9


def test_sheets_project_card_is_not_hardcoded_to_the_base_demo(llm_env):
    from ui import sheets_view
    other = demo_started("run_set_3").session_state["run_result"]
    card = sheets_view.project_card(other)
    assert card["issues"] == other["summary"]["z"] == 15 and card["impact_som"] != "1 378 030 сом"
    assert card["red"] + card["yellow"] + card["green"] == sum(other["summary"]["statuses"].values())


# ---------- «Как работает ИИ» ----------
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
    assert "Что изменено:" in html and "ИИ не подтвердил совпадение, нужна проверка" in html and "Если кандидатов не было, поведение прежнее" in html
    assert "ещё не сделано" not in html and "будут помечаться" not in html
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


def test_rationale_page_keeps_the_essentials_and_hides_details(llm_env):
    at = AppTest.from_function(rationale_app, default_timeout=180).run()
    assert not at.exception
    assert [e.label for e in at.expander] == ["Подробности: расхождения по режимам, пары названий и примеры"] and at.expander[0].proto.expanded is False
    html = body(at)
    assert html.index("Без ИИ и с ИИ") < html.index("Как ИИ и код делят работу") < html.index("Где ИИ ошибается") < html.index("Шесть примеров из сохранённых")
    assert "Исходные файлы" not in html and not at.selectbox                              # просмотр файлов переехал на «Исходные таблицы»
