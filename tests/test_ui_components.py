"""ui/components.py: HTML карточек, светофора, метрик и таблицы позиций (без запуска Streamlit)."""
import pandas as pd

from ui import components as c
from ui.data import positions_view, traffic_segments


SIDES = {"left": {"label": "В ВОР", "name": "Арматура А500 d12", "value": "9,5 т", "where": "vor.xlsx · строка 2", "names_differ": True},
         "right": {"label": "В актах", "rows": [{"name": "Арм. А500 <Ø12>", "value": "5 т", "where": "act_1.xlsx · строка 3"},
                                                {"name": "Арм. А500 <Ø12>", "value": "6,4 т", "where": "act_2.xlsx · строка 4"}],
                   "total": "Всего 11,4 т"}}


def card(**over):
    base = {"title": "Работа <b>x</b>", "type_label": "Превышение объёма", "severity": "high", "severity_label": "высокая",
            "phrase": "В актах 12 м3 при 10 м3 в ВОР (+20,0%)", "impact_text": "45 000 сом", "ai": True, "note": "",
            "sources": ["Акт · a.xlsx · лист «Акт» · строка 5", "ВОР · v.xlsx · лист «ВОР» · строка 2"], "ai_pairs": [], "ai_none": None,
            "impact_value": 45000.0, "sides": SIDES}
    return {**base, **over}


def test_issue_card_has_stripe_badges_phrase_impact_sources_and_escapes_html():
    html = c.issue_card_html(card())
    assert "background:#C62828" in html and "Превышение объёма" in html and "важность: высокая" in html
    assert "ИИ помог сопоставить" in html and "45 000 сом" in html and "возможное влияние" in html
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


def test_sides_html_shows_vor_and_act_as_written_and_groups_act_rows():
    html = c.sides_html(SIDES)
    assert html.count('class="side ') == 2 and "side-vor" in html and "side-act" in html
    assert "В ВОР" in html and "«Арматура А500 d12»" in html and "9,5 т" in html
    assert html.count("«Арм. А500 &lt;Ø12&gt;»") == 1                                 # одинаковое название акта показано один раз
    assert "act_1.xlsx: 5 т<br>act_2.xlsx: 6,4 т" in html and "Всего 11,4 т" in html
    assert "Названия записаны по-разному в разных документах" in html and "<Ø12>" not in html
    none = {"left": {"label": "В ВОР", "name": None, "value": "такой позиции не найдено", "where": "", "names_differ": False},
            "right": {"label": "В акте", "rows": [{"name": "Разборка пола", "value": "873 м2", "where": "act_1.xlsx · строка 16"}], "total": ""}}
    html = c.sides_html(none)
    assert "такой позиции не найдено" in html and "side-none" in html and "Названия записаны" not in html and "side-total" not in html


def test_issue_card_shows_amount_and_reason_when_amount_is_empty():
    html = c.issue_card_html(card())
    assert "45 000 сом" in html and "возможное влияние" in html and 'class="sides"' in html
    empty = c.issue_card_html(card(impact_value=None, impact_text="— (нет цены в смете)"))
    assert "нет цены в смете" in empty and "45 000" not in empty


def test_showcase_components():
    hero = c.hero_html("Заголовок <b>", "Лид", "Демо", "Заметка")
    assert "hero-title" in hero and "Заголовок &lt;b&gt;" in hero and "Заметка" in hero and "Демо" in hero
    trio = c.trio_html([("А", "а"), ("Б", "б"), ("В", "в")])
    assert trio.count("trio-item") == 3 and ">3<" in trio
    assert 'claim-warn' in c.claim_html("x", warn=True) and 'claim-warn' not in c.claim_html("x")
