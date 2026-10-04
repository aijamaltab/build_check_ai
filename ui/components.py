"""Компоненты экрана: HTML карточек, бейджей, светофора и диаграммы. Тексты экранируются, стили в ui/styles.py."""
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from ui.data import MAX_AI_PAIRS_ON_CARD, SEVERITY_COLOR, STATUS_ROW_FILL, fmt_conf, fmt_num


def render(html: str) -> None:
    st.markdown(html, unsafe_allow_html=True)       # HTML без пустых строк и отступов, иначе markdown примет его за код


def stretch(call, *args, **kwargs):
    """Во всю ширину: новый параметр width="stretch", на старых версиях Streamlit use_container_width."""
    try:
        return call(*args, width="stretch", **kwargs)
    except TypeError:
        return call(*args, use_container_width=True, **kwargs)


def header_html(title: str, subtitle: str, pill: str) -> str:
    return (f'<div><span class="app-title">{escape(title)}</span><span class="pill">{escape(pill)}</span></div>'
            f'<div class="app-sub">{escape(subtitle)}</div>')


def banner_html(text: str) -> str:
    return f'<div class="banner" role="status">{escape(text)}</div>'


def metric_cards_html(cards: list) -> str:
    """cards: [{label, value, note}] -> сетка 4 колонки на десктопе и 2 на телефоне."""
    items = "".join(f'<div class="metric-card"><div class="metric-label">{escape(c["label"])}</div>'
                    f'<div class="metric-value">{escape(c["value"])}</div>'
                    + (f'<div class="metric-note">{escape(c["note"])}</div>' if c.get("note") else "") + "</div>" for c in cards)
    return f'<div class="metric-grid">{items}</div>'


def traffic_html(segments: list) -> str:
    """Одна полоса из трёх сегментов, ширина пропорциональна числу позиций (не уже 24%); слово и число внутри каждого сегмента."""
    total = sum(s["count"] for s in segments) or 1
    parts = "".join(
        f'<div class="seg" role="img" aria-label="{escape(s["label"])}" style="background:{s["bg"]};color:{s["fg"]};flex:{max(s["count"], 1) / total:.4f}">'
        f'<div class="seg-word">{escape(s["word"])}</div><div class="seg-count">{s["count"]} позиций</div></div>'
        for s in segments)
    return f'<div class="traffic">{parts}</div>'


def section_html(title: str, sub: str = "") -> str:
    return f'<div class="section-title">{escape(title)}</div>' + (f'<div class="section-sub">{escape(sub)}</div>' if sub else "")


def badge(text: str, kind: str = "") -> str:
    return f'<span class="badge {kind}">{escape(text)}</span>'


DOC_ROLE = {"act": "Акт", "estimate": "Смета", "vor": "ВОР"}


def ai_box_html(c: dict) -> str:
    """Блок «Что сделал ИИ»: пары названий до и после (документ -> ВОР), уверенность и причина из ответа модели, либо «ИИ не нашёл пару»."""
    lines = ""
    for p in c["ai_pairs"][:MAX_AI_PAIRS_ON_CARD]:
        meta = f"уверенность {fmt_conf(p['confidence'])}" + (f" · причина: {p['reason']}" if p["reason"] else "")
        lines += (f'<div class="ai-pair"><div class="ai-names"><span class="ai-before">{DOC_ROLE.get(p["doc_type"], "Док.")}: «{escape(p["doc"])}»</span>'
                  f'<span class="ai-arrow"> → </span><span class="ai-after">ВОР: «{escape(p["vor"])}»</span></div>'
                  f'<div class="ai-meta">{escape(meta)}</div></div>')
    extra = len(c["ai_pairs"]) - MAX_AI_PAIRS_ON_CARD
    if extra > 0:
        lines += f'<div class="ai-meta">и ещё {extra} пар(ы) названий</div>'
    if c["ai_none"]:
        n = c["ai_none"]
        meta = f"уверенность {fmt_conf(n['confidence'])}" + (f" · причина: {n['reason']}" if n["reason"] else "")
        lines += f'<div class="ai-pair"><div class="ai-names">ИИ просмотрел весь список ВОР и не нашёл пару</div><div class="ai-meta">{escape(meta)}</div></div>'
    if not lines:
        return ""
    return f'<div class="ai-box"><div class="ai-title">Что сделал ИИ</div>{lines}</div>'


def issue_card_html(c: dict) -> str:
    """Карточка расхождения: цветная полоса важности, название, бейджи, фраза, влияние, пометка, источники."""
    color = SEVERITY_COLOR[c["severity"]]
    badges = badge(c["type_label"]) + badge(f"важность: {c['severity_label']}", f"badge-{c['severity']}")
    if c["ai"]:
        badges += badge("ИИ помог сопоставить", "badge-ai")
    sources = "<br>".join(escape(s) for s in c["sources"])
    note = f'<div class="issue-note">{escape(c["note"])}</div>' if c["note"] else ""
    return (f'<div class="issue-card"><div class="issue-bar" style="background:{color}"></div><div class="issue-body">'
            f'<div class="issue-title">{escape(c["title"])}</div><div>{badges}</div>'
            f'<div class="issue-phrase">{escape(c["phrase"])}</div>'
            f'<div class="issue-impact">Влияние: {escape(c["impact_text"])}</div>{note}{ai_box_html(c)}'
            f'<div class="issue-src">{sources}</div></div></div>')


def cards_html(cards: list) -> str:
    return "".join(issue_card_html(c) for c in cards)


def bar_chart(frame: pd.DataFrame, color: str = "#1F3A5F") -> None:
    """Горизонтальные столбцы с числами на концах (подписи типов длинные, так читаемее и на телефоне)."""
    top = float(frame["value"].max())
    base = alt.Chart(frame).encode(
        y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=260, labelFontSize=13, ticks=False, domain=False)),
        x=alt.X("value:Q", title=None, axis=None, scale=alt.Scale(domain=[0, top * 1.3 if top > 0 else 1])))
    bars = base.mark_bar(color=color, cornerRadiusEnd=4, size=22)
    labels = base.mark_text(align="left", dx=6, fontSize=13, color="#1B2430").encode(text="text:N")
    chart = (bars + labels).properties(height=44 * len(frame) + 10).configure_view(strokeWidth=0)
    stretch(st.altair_chart, chart)


def style_positions(frame: pd.DataFrame):
    """Подсветка строк светофора светлой заливкой с тёмным текстом; служебная колонка _status скрыта. Числа заранее строками
    (пустые «—»): иначе Streamlit показывает пустые ячейки как None; выравнивание вправо задаётся стилем."""
    status = frame["_status"].tolist()
    shown = frame.drop(columns=["_status"]).copy()
    numeric = ["План", "Факт", "Выполнено, %"]
    for col in numeric:
        shown[col] = shown[col].map(fmt_num)
    styler = shown.style.apply(lambda row: [f"background-color: {STATUS_ROW_FILL[status[row.name]]}; color: #1B1B1B"] * len(row), axis=1)
    return styler.set_properties(subset=numeric, **{"text-align": "right"})


def ai_line_html(text: str) -> str:
    return f'<div class="ai-line">{escape(text)}</div>'


def compare_html(rows: list, note: str) -> str:
    """Блок «Без ИИ и с ИИ» в две колонки. rows: [(показатель, без ИИ, с ИИ)]."""
    def column(title, idx, cls):
        body = "".join(f'<div class="cmp-row"><span class="cmp-label">{escape(r[0])}</span><span class="cmp-value">{escape(r[idx])}</span></div>'
                       for r in rows)
        return f'<div class="cmp-col {cls}"><div class="cmp-title">{escape(title)}</div>{body}</div>'
    return (f'<div class="cmp-grid">{column("Без ИИ (только правила)", 1, "")}{column("С ИИ", 2, "cmp-ai")}</div>'
            f'<div class="note-small">{escape(note)}</div>')


def examples_html(examples: list) -> str:
    """Карточки «Как ИИ и код делят работу»: название в ВОР, в акте, правило кода, ответ ИИ, проверка кода."""
    cards = ""
    for e in examples:
        vor = f"«{escape(e['vor'])}»" if e["vor"] else "такой позиции в ВОР не найдено"
        cards += ('<div class="ex-card">'
                  f'<div class="ex-row"><span class="ex-label">В ВОР</span><span>{vor}</span></div>'
                  f'<div class="ex-row"><span class="ex-label">В акте</span><span>«{escape(e["doc"])}»</span></div>'
                  f'<div class="ex-row"><span class="ex-label">Код (правило)</span><span>{escape(e["code_rule"])}</span></div>'
                  f'<div class="ex-row ex-ai"><span class="ex-label">ИИ решил</span><span>{escape(e["ai"])}</span></div>'
                  f'<div class="ex-row"><span class="ex-label">Код проверил</span><span>{escape(e["code_check"])}</span></div></div>')
    return f'<div class="ex-grid">{cards}</div>'
