"""ui/components.py: HTML карточек, светофора, метрик и таблицы позиций (без запуска Streamlit)."""
import pandas as pd

from ui import components as c
from ui.data import positions_view, traffic_segments


def card(**over):
    base = {"title": "Работа <b>x</b>", "type_label": "Превышение объёма", "severity": "high", "severity_label": "высокая",
            "phrase": "В актах 12 м3 при 10 м3 в ВОР (+20,0%)", "impact_text": "45 000 сом", "ai": True, "note": "",
            "sources": ["Акт · a.xlsx · лист «Акт» · строка 5", "ВОР · v.xlsx · лист «ВОР» · строка 2"], "ai_pairs": [], "ai_none": None}
    return {**base, **over}


def test_issue_card_has_stripe_badges_phrase_impact_sources_and_escapes_html():
    html = c.issue_card_html(card())
    assert "background:#C62828" in html and "Превышение объёма" in html and "важность: высокая" in html
    assert "ИИ помог сопоставить" in html and "Влияние: 45 000 сом" in html
    assert "Акт · a.xlsx · лист «Акт» · строка 5<br>ВОР · v.xlsx" in html
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html                 # текст из данных экранируется
    assert "\n\n" not in html and not html.startswith(" ")                          # markdown не примет за блок кода


def test_card_without_ai_and_with_note():
    html = c.issue_card_html(card(ai=False, severity="low", severity_label="низкая", note="Низкая уверенность, требует проверки"))
    assert "ИИ помог сопоставить" not in html and "background:#9AA3AE" in html and "issue-note" in html


def test_metric_cards_and_traffic_html():
    html = c.metric_cards_html([{"label": "Позиций проверено", "value": "180"}, {"label": "Влияние", "value": "1 378 030", "note": "оценка"}])
    assert html.count('class="metric-card"') == 2 and "1 378 030" in html and "оценка" in html
    summary = {"statuses": {"red": 11, "yellow": 7, "green": 30}}
    bar = c.traffic_html(traffic_segments(summary))
    assert bar.count('class="seg"') == 3 and "Красные: 11 позиций" in bar and "#C62828" in bar and "#F9A825" in bar and "#2E7D32" in bar
    assert "color:#1B1B1B" in bar                                                    # на жёлтом тёмный текст (контраст)


def test_style_positions_shows_dash_for_empty_and_colors_rows():
    positions = pd.DataFrame([{"name": "А", "unit_label": "м2", "plan_qty": None, "fact_qty": 5.0, "pct": None, "status": "red"},
                              {"name": "Б", "unit_label": "т", "plan_qty": 9.5, "fact_qty": 11.4, "pct": 120.0, "status": "green"}])
    styler = c.style_positions(positions_view(positions))
    html = styler.to_html()
    assert "—" in html and "None" not in html and "nan" not in html.lower()
    assert "#FDECEA" in html and "#E8F5E9" in html and "9,5" in html and "_status" not in html


def test_ai_box_shows_before_after_confidence_reason_and_escapes():
    pairs = [{"doc_type": "act", "doc": "Разр. грунта <i>", "vor": "Разработка грунта", "confidence": 0.95, "reason": "сокращение", "stage": "llm"},
             {"doc_type": "estimate", "doc": "А", "vor": "Б", "confidence": 1.0, "reason": "", "stage": "llm_row"}]
    html = c.issue_card_html(card(ai_pairs=pairs))
    assert "Что сделал ИИ" in html and "Акт: «Разр. грунта &lt;i&gt;»" in html and "ВОР: «Разработка грунта»" in html
    assert "уверенность 0,95 · причина: сокращение" in html and "Смета: «А»" in html and "уверенность 1,00" in html
    assert "<i>" not in html and "\n\n" not in html


def test_ai_box_limits_pairs_and_shows_not_found():
    many = [{"doc_type": "act", "doc": f"д{i}", "vor": f"в{i}", "confidence": 0.9, "reason": "р", "stage": "llm"} for i in range(5)]
    html = c.ai_box_html(card(ai_pairs=many))
    assert html.count('class="ai-pair"') == 3 and "и ещё 2 пар(ы) названий" in html
    none = c.ai_box_html(card(ai_none={"confidence": 0.9, "reason": "в ВОР нет такой позиции"}))
    assert "не нашёл пару" in none and "уверенность 0,90 · причина: в ВОР нет такой позиции" in none
    assert c.ai_box_html(card()) == "" and "Что сделал ИИ" not in c.issue_card_html(card())


def test_compare_examples_and_ai_line_html():
    html = c.compare_html([("Возможных расхождений", "18", "13"), ("Найдено заложенных", "8 из 12", "12 из 12")],
                          "Синтетические данные, оценка ориентировочная.")
    assert "Без ИИ (только правила)" in html and "С ИИ" in html and "8 из 12" in html and "12 из 12" in html
    assert "оценка ориентировочная" in html
    ex = [{"kind": "pair_accepted", "vor": "Разработка <b>", "doc": "Разр.", "code_rule": "правило", "ai": "решил", "code_check": "проверил"}]
    html = c.examples_html(ex)
    assert html.count('class="ex-card"') == 1 and "Код (правило)" in html and "ИИ решил" in html and "Код проверил" in html
    assert "<b>" not in html and "&lt;b&gt;" in html
    assert "такой позиции в ВОР не найдено" in c.examples_html([{**ex[0], "vor": None}])
    assert "код считает и проверяет числа" in c.ai_line_html("ИИ читает и сопоставляет названия, код считает и проверяет числа")
