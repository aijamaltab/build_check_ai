import os

# Деплой без ключа Gemini: только кэш ответов (data/cache/llm), API не вызывается. Должно стоять до импорта проекта.
os.environ.setdefault("LLM_CACHE_ONLY", "1")

import logging  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import streamlit as st  # noqa: E402

from src.pipeline import run_pipeline  # noqa: E402
from ui.data import fmt_num, impact_split, issues_table, load_results  # noqa: E402

ROOT = Path(__file__).parent
DEMO_DIR = ROOT / "data" / "synthetic"
DB_DIR = Path(tempfile.gettempdir()) / "hackathon_ai_demo"
DISCLAIMER = ("Система показывает возможные расхождения между документами и не доказывает фактическое выполнение работ. "
              "Каждое расхождение требует проверки; окончательное решение за специалистом.")
log = logging.getLogger("app")


@st.cache_resource(show_spinner="Строим результат из демо-проекта…")
def build_demo() -> dict:
    """Один раз за запуск сервера: база из data/synthetic в режиме llm (ответы из кэша), затем чтение только на чтение."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = DB_DIR / "demo.db"
    summary = run_pipeline(DEMO_DIR, db, "llm")
    results = load_results(db)
    results["files"] = summary["files"]
    log.warning("demo built: mode=%s files=%s issues=%s", summary["mode"], summary["files"], summary["z"])
    return results


st.set_page_config(page_title="Сверка строительных документов", layout="wide")
st.title("Сверка строительных документов")
st.info("Демо, синтетические данные")

results = build_demo()
summary, issues, positions = results["summary"], results["issues"], results["positions"]
if not results["files"] or not summary:
    st.error("Файлы не найдены")
    st.stop()

if summary["banner"]:
    note = " (запрошен режим llm)" if summary["requested_mode"] == "llm" else ""
    st.warning(summary["banner"] + note)
st.caption("Режим: " + ("С ИИ (ответы Gemini из кэша демо)" if summary["mode"] == "llm" else "Без ИИ (базовый режим)"))
st.caption(DISCLAIMER)

st.subheader(f"Проверено {summary['n']} позиций, не распознано {summary['m']}, не сопоставлено {summary['k']}, "
             f"из них требует проверки {summary['a']}, не сопоставимо {summary['l']}; расхождений {summary['z']}")
for name in summary["documents_with_errors"]:
    st.warning(f"Файл {name} требует проверки")

ai = summary["ai"]
if summary["mode"] == "llm" and ai["pairs_no_decision"] + ai["rows_no_decision"] > 0:
    st.info(f"ИИ-ответы из кэша демо; для новых названий {ai['rows_no_decision']} строк требуют проверки")

col_red, col_yellow, col_green = st.columns(3)
statuses = summary["statuses"]
col_red.metric("Красные позиции", statuses["red"])
col_yellow.metric("Жёлтые позиции", statuses["yellow"])
col_green.metric("Зелёные позиции", statuses["green"])
if summary["caveat"]:
    st.warning(summary["caveat"])

split = impact_split(issues)
if summary["mode"] == "llm":
    st.metric("Возможное влияние на бюджет", f"{fmt_num(summary['impact_som'])} сом")
else:
    st.metric("Возможное влияние на бюджет (высокая уверенность)", f"{fmt_num(split['high'])} сом")
    if split["n_low"]:
        st.caption(f"ещё {split['n_low']} расхождений низкой уверенности (без ИИ), возможное влияние {fmt_num(split['low'])} сом")
st.caption("Оценка размера возможных расхождений по документам, не вывод о потерях.")

st.subheader("Возможные расхождения")
st.dataframe(issues_table(issues, positions), hide_index=True)

with st.expander("Светофор по позициям"):
    shown = positions.rename(columns={"name": "Работа", "unit_label": "Ед.", "plan_qty": "План", "fact_qty": "Факт", "pct": "%",
                                      "status": "Статус"})[["Работа", "Ед.", "План", "Факт", "%", "Статус"]]
    st.dataframe(shown, hide_index=True)
