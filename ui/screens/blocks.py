"""Общие блоки страниц: метрики, светофор, главные расхождения, сверочная ведомость. Страницы только собирают их вместе."""
import streamlit as st

from ui import components as ui
from ui.data import build_cards, fmt_num, headline_metrics, sort_issues, traffic_legend, traffic_segments
from ui.ledger import render_ledger
from ui.ledger_data import build_ledger

FOOTER = '<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>'
TOP_N = 3
ROWS_LABEL = "Строк в документах"
ROWS_NOTE = "ВОР, смета и акты, без договора"


def footer() -> None:
    ui.render(FOOTER)


def metrics_block(summary: dict, issues, positions) -> None:
    """Четыре метрики. Первая это строки документов (summary['n']), а не позиции светофора: их число показано рядом со светофором."""
    m = headline_metrics(summary, issues, positions)
    ui.render(ui.metric_cards_html([
        {"label": ROWS_LABEL, "value": fmt_num(m["positions"]), "note": ROWS_NOTE},
        {"label": "Возможных расхождений", "value": fmt_num(m["issues"])},
        {"label": "Возможное влияние на бюджет, сом", "value": fmt_num(m["impact"]), "note": "Оценка размера возможных расхождений, не вывод о потерях"},
        {"label": "Позиции с отклонением от плана", "value": fmt_num(m["review_positions"]),
         "note": "красные и жёлтые позиции: расхождение или выполнение меньше плана"}]))
    if m["impact_extra_n"]:
        ui.render(f'<div class="note-small">В сумму не входят ещё {m["impact_extra_n"]} расхождений низкой уверенности '
                  f'(без ИИ), возможное влияние {fmt_num(m["impact_extra"])} сом.</div>')


def traffic_block(summary: dict) -> None:
    """Полоса светофора и легенда (один раз на странице)."""
    total = sum(int(v) for v in summary["statuses"].values())
    ui.render(ui.section_html("Светофор по позициям", f"Позиций ВОР в светофоре: {total}"))
    ui.render(ui.traffic_html(traffic_segments(summary)))
    ui.render(f'<div class="legend">{traffic_legend()}</div>')
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
