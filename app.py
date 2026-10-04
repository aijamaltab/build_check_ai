import os

# Деплой без ключа Gemini: только кэш ответов (data/cache/llm), API не вызывается. Должно стоять до импорта проекта.
os.environ.setdefault("LLM_CACHE_ONLY", "1")

import logging  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import streamlit as st  # noqa: E402

from src.pipeline import run_pipeline  # noqa: E402
from ui import components as ui  # noqa: E402
from ui.data import (TYPE_RU, TYPE_ORDER, build_cards, cards_frame, chart_frames, fmt_num, filter_issues, headline_metrics,  # noqa: E402
                     load_results, positions_view, quality_compare, sort_issues, traffic_legend, traffic_segments)
from ui.styles import inject  # noqa: E402

ROOT = Path(__file__).parent
DEMO_DIR = ROOT / "data" / "synthetic"
DB_DIR = Path(tempfile.gettempdir()) / "hackathon_ai_demo"
MODES = {"С ИИ": "llm", "Без ИИ": "rules_only"}
SEVERITY_CHOICES = {"Все": "all", "Высокая": "high", "Средняя": "medium", "Низкая": "low"}
STATUS_CHOICES = {"Все": "all", "Красные": "red", "Жёлтые": "yellow", "Зелёные": "green"}
AI_LINE = "ИИ читает и сопоставляет названия, код считает и проверяет числа"
QUALITY_NOTE = "Синтетические данные, оценка ориентировочная."
WITHOUT_AI_BANNER = "ИИ выключен: похожие названия не склеиваются, ложных расхождений больше"
log = logging.getLogger("app")


@st.cache_resource(show_spinner="Строим результат из демо-проекта…")
def build_demo(mode: str) -> dict:
    """Один раз на режим за запуск сервера: отдельный файл базы на режим, дальше только чтение."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = DB_DIR / f"demo_{mode}.db"
    summary = run_pipeline(DEMO_DIR, db, mode)
    results = load_results(db)
    results["files"] = summary["files"]
    log.warning("demo built: requested=%s mode=%s files=%s issues=%s", mode, summary["mode"], summary["files"], summary["z"])
    return results


def segmented(label: str, options: list, default: str, key: str) -> str:
    """st.segmented_control, а если версии Streamlit не хватает, горизонтальный st.radio."""
    if hasattr(st, "segmented_control"):
        picked = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed")
        return picked or default
    return st.radio(label, options, index=options.index(default), horizontal=True, key=key, label_visibility="collapsed")


st.set_page_config(page_title="Сверка строительных документов", layout="wide", initial_sidebar_state="collapsed")
inject()

# 1. шапка (режим ниже: его знаем только после выбора переключателя)
ui.render(ui.header_html("Сверка строительных документов", "ВОР · смета · договор · акты в одной таблице",
                         "Демо на синтетических данных"))
ui.render(ui.ai_line_html(AI_LINE))
# 2. переключатель «С ИИ / Без ИИ»
mode_label = segmented("Режим", list(MODES), "С ИИ", "mode")
mode = MODES[mode_label]
try:
    results = build_demo(mode)
except Exception:  # noqa: BLE001: пользователю человеческая ошибка, подробности в логе
    log.exception("demo build failed")
    st.error("Не удалось собрать результат из демо-проекта. Обновите страницу; если ошибка повторяется, сообщите разработчикам.")
    st.stop()

summary, issues, positions = results["summary"], results["issues"], results["positions"]
if not results["files"] or not summary:
    st.error("Файлы демо-проекта не найдены, сверять нечего.")
    st.stop()

actual = summary["mode"]
mode_line = "Режим: С ИИ (ответы Gemini из кэша)" if actual == "llm" else "Режим: Без ИИ (только правила)"

ui.render(f'<div class="mode-line">{mode_line}</div>')
if actual != mode:                                   # запросили llm, а кэша нет: pipeline сам перешёл на правила
    ui.render(ui.banner_html(summary["banner"] or "ИИ-режим недоступен, использован базовый режим"))
elif actual == "rules_only":
    ui.render(ui.banner_html(WITHOUT_AI_BANNER))

# 3. карточки-метрики
m = headline_metrics(summary, issues, positions)
cards = [{"label": "Позиций проверено", "value": fmt_num(m["positions"])},
         {"label": "Возможных расхождений", "value": fmt_num(m["issues"])},
         {"label": "Возможное влияние на бюджет, сом", "value": fmt_num(m["impact"]),
          "note": "Оценка размера возможных расхождений, не вывод о потерях"},
         {"label": "Позиции для проверки", "value": fmt_num(m["review_positions"]), "note": "красные и жёлтые позиции"}]
ui.render(ui.metric_cards_html(cards))
if m["impact_extra_n"]:
    ui.render(f'<div class="note-small">В сумму не входят ещё {m["impact_extra_n"]} расхождений низкой уверенности '
              f'(без ИИ), возможное влияние {fmt_num(m["impact_extra"])} сом.</div>')
if summary["a"] and actual == "rules_only":
    ui.render(f'<div class="note-small">{summary["a"]} строк требуют проверки ИИ, без него они не сопоставлены.</div>')
ai = summary["ai"]
if actual == "llm" and ai["pairs_no_decision"] + ai["rows_no_decision"] > 0:
    ui.render(f'<div class="note-small">ИИ-ответы из кэша демо; для новых названий {ai["rows_no_decision"]} строк требуют проверки.</div>')

# 3а. где работает ИИ: сравнение режимов и разделение работы (из режима llm, то есть из кэша ответов)
try:
    with_ai = build_demo("llm")
    without_ai = build_demo("rules_only")
except Exception:  # noqa: BLE001
    with_ai = without_ai = None
if with_ai and without_ai and with_ai["summary"]["mode"] == "llm":
    ui.render(ui.section_html("Без ИИ и с ИИ", "Те же документы, два режима"))
    ui.render(ui.compare_html(quality_compare(without_ai["issues"], with_ai["issues"]), QUALITY_NOTE))
    if with_ai["ai_examples"]:
        ui.render(ui.section_html("Как ИИ и код делят работу",
                                  "ИИ предлагает пару названий, код применяет правила и проверяет единицы и числа"))
        ui.render(ui.examples_html(with_ai["ai_examples"]))

# 4. светофор
ui.render(ui.section_html("Светофор по позициям"))
ui.render(ui.traffic_html(traffic_segments(summary)))
ui.render(f'<div class="legend">{traffic_legend()}</div>')
if summary["caveat"]:
    ui.render(ui.banner_html(summary["caveat"]))

# 5. аналитика
by_count, by_impact = chart_frames(issues)
left, right = st.columns(2)
with left:
    ui.render(ui.section_html("Расхождения по типам"))
    ui.bar_chart(by_count)
with right:
    ui.render(ui.section_html("Влияние на бюджет по типам, сом"))
    ui.bar_chart(by_impact, color="#2F5D8C")

# 6. список расхождений
ui.render(ui.section_html("Возможные расхождения", "Сначала высокая важность, внутри по влиянию на бюджет. Каждое требует проверки специалистом."))
view = segmented("Вид", ["Карточки", "Таблица"], "Карточки", "view")
c1, c2, c3 = st.columns([2, 2, 2])
with c1:
    severity = SEVERITY_CHOICES[segmented("Важность", list(SEVERITY_CHOICES), "Все", "severity")]
with c2:
    chosen = st.multiselect("Тип", [TYPE_RU[t] for t in TYPE_ORDER], placeholder="Все типы")
with c3:
    query = st.text_input("Поиск по названию работы", placeholder="например, арматура")
types = [t for t in TYPE_ORDER if TYPE_RU[t] in chosen]
shown = sort_issues(filter_issues(issues, positions, severity, types, query))
cards_list = build_cards(shown, positions)
st.caption(f"Показано {len(cards_list)} из {len(issues)}")
if not cards_list:
    st.info("По выбранным фильтрам расхождений нет.")
elif view == "Карточки":
    ui.render(ui.cards_html(cards_list))
else:
    ui.stretch(st.dataframe, cards_frame(cards_list), hide_index=True, height=max(500, 36 * len(cards_list) + 40),
               column_config={"Влияние, сом": st.column_config.NumberColumn("Влияние, сом", format="localized"),
                              "Источник": st.column_config.TextColumn("Источник", width="large"),
                              "Что не так": st.column_config.TextColumn("Что не так", width="large")})

# 7. светофор по позициям
ui.render(ui.section_html("Позиции", "Красные сверху. Цвет подкреплён словом в колонке «Статус»."))
status = STATUS_CHOICES[segmented("Цвет", list(STATUS_CHOICES), "Все", "status")]
table = positions_view(positions, status)
ui.stretch(st.dataframe, ui.style_positions(table), hide_index=True, height=500)

# 8-9. как работает и подвал
ui.render('<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>')
