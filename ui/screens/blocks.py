"""Общие блоки страниц: метрики, светофор, главные расхождения, сверочная ведомость. Страницы только собирают их вместе."""
import streamlit as st

from ui import components as ui
from ui.data import build_cards, fmt_num, headline_metrics, sort_issues, traffic_legend_short, traffic_segments
from ui.ledger import render_ledger
from ui.ledger_data import build_issue_rows, build_ledger

FOOTER = '<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>'
TOP_N = 3
ROWS_LABEL = "Строк в документах"
ROWS_NOTE = "ВОР, смета и акты, без договора"


def footer() -> None:
    ui.render(FOOTER)


def metrics_block(summary: dict, issues, positions) -> None:
    """Пять плиток. «Строк в документах» (summary['n']) и «Позиций ВОР» (позиции светофора) это разные числа, поэтому плиток две."""
    m = headline_metrics(summary, issues, positions)
    ui.render(ui.tiles_html([
        {"label": ROWS_LABEL, "value": fmt_num(m["positions"]), "hint": ROWS_NOTE},
        {"label": "Позиций ВОР", "value": fmt_num(sum(int(v) for v in summary["statuses"].values())), "hint": "Позиции ведомости в светофоре"},
        {"label": "Расхождений", "value": fmt_num(m["issues"])},
        {"label": "Возможное влияние, сом", "value": fmt_num(m["impact"]), "hint": "Оценка размера возможных расхождений, не вывод о потерях"},
        {"label": "Позиций с отклонением от плана", "value": fmt_num(m["review_positions"]), "hint": "красные и жёлтые позиции"}]))
    ui.render(f'<div class="note-small">Строки: {ROWS_NOTE}. Влияние на бюджет: оценка размера возможных расхождений, не вывод о потерях.</div>')
    if m["impact_extra_n"]:
        ui.render(f'<div class="note-small">В сумму не входят ещё {m["impact_extra_n"]} расхождений низкой уверенности '
                  f'(без ИИ), возможное влияние {fmt_num(m["impact_extra"])} сом.</div>')


def traffic_block(summary: dict) -> None:
    """Тонкая полоса светофора с числами и пояснением цветов одной строкой (один раз на странице)."""
    ui.render(ui.traffic_thin_html(traffic_segments(summary), traffic_legend_short()))
    if summary.get("caveat"):
        ui.render(ui.banner_html(summary["caveat"]))


def top_issues_block(issues, positions, n: int = TOP_N) -> None:
    """Главные расхождения компактными строками: сначала высокая важность, внутри по влиянию на бюджет."""
    ui.render(ui.section_html("Главные расхождения", f"{min(n, len(issues))} из {len(issues)}. Каждое требует проверки специалистом."))
    if issues.empty:
        st.info("Расхождений не найдено.")
        return
    ui.render(ui.issue_rows_html(build_cards(sort_issues(issues).head(n), positions)))


def ledger_block(results: dict) -> None:
    """Сверочная ведомость: таблица позиций с подсветкой расхождений, подсказками и панелью сведений."""
    if results.get("positions") is None or results["positions"].empty or results.get("items") is None:
        st.info("Данные по позициям отсутствуют.")
        return
    render_ledger(build_ledger(results))


def issues_table_block(results: dict) -> None:
    """Таблица «Возможные расхождения»: тот же компонент, режим «только расхождения»."""
    if results["issues"].empty:
        st.info("Расхождений не найдено.")
        return
    render_ledger(build_issue_rows(results), mode="issues")
