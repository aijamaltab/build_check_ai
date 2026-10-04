"""Компоненты экрана: HTML карточек, бейджей, светофора и диаграммы. Тексты экранируются, стили в ui/styles.py."""
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from ui.data import MAX_AI_PAIRS_ON_CARD, SEVERITY_COLOR, STATUS_ROW_FILL, fmt_conf, fmt_num

DOC_ROLE = {"act": "Акт", "estimate": "Смета", "vor": "ВОР"}
CHART_COLOR = "#2E5E4E"


def render(html: str) -> None:
    st.markdown(html, unsafe_allow_html=True)       # HTML без пустых строк и отступов, иначе markdown примет его за код


def stretch(call, *args, **kwargs):
    """Во всю ширину: новый параметр width="stretch", на старых версиях Streamlit use_container_width."""
    try:
        return call(*args, width="stretch", **kwargs)
    except TypeError:
        return call(*args, use_container_width=True, **kwargs)


# ---------- страница-витрина ----------
def hero_html(title: str, lead: str, pill: str, note: str = "") -> str:
    return (f'<div class="hero"><span class="pill">{escape(pill)}</span><div class="hero-title">{escape(title)}</div>'
            f'<div class="hero-lead">{escape(lead)}</div>' + (f'<div class="hero-note">{escape(note)}</div>' if note else "") + "</div>")


def trio_html(items: list) -> str:
    """Три пункта в ряд (на телефоне друг под другом): [(заголовок, текст)] с номерами."""
    cells = "".join(f'<div class="trio-item"><div class="trio-num">{i}</div><div class="trio-title">{escape(t)}</div>'
                    f'<div class="trio-text">{escape(text)}</div></div>' for i, (t, text) in enumerate(items, 1))
    return f'<div class="trio">{cells}</div>'


def claim_html(text: str, warn: bool = False) -> str:
    return f'<div class="claim{" claim-warn" if warn else ""}">{escape(text)}</div>'


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


def fileinfo_html(info: dict) -> str:
    """Структура выбранного файла: роль документа, найденный шаблон, колонки, которые распознаёт программа, итоги чтения."""
    facts = "".join(f"<span>{escape(k)}: <b>{escape(str(v))}</b></span>" for k, v in info["facts"])
    chips = "".join(f'<span class="chip">{escape(c)}</span>' for c in info["columns"])
    return ('<div class="fileinfo"><div class="fileinfo-head">'
            f'<span class="fileinfo-name">{escape(info["file"])}</span>{badge(info["role"])}{badge("шаблон: " + info["template"], "badge-ai")}</div>'
            f'<div class="fileinfo-facts">{facts}</div>'
            f'<div class="side-label">{escape(info["columns_label"])}</div><div class="chips">{chips}</div></div>')


# ---------- карточка расхождения ----------
def sides_html(sides: dict) -> str:
    """Что в ВОР (смете, договоре) и что в акте, как написано: две панели рядом (на телефоне друг под другом)."""
    left, right = sides["left"], sides["right"]
    if left["name"]:
        left_body = f'<div class="side-name">«{escape(left["name"])}»</div>'
    else:
        left_body = ""
    value = f'<div class="side-value">{escape(left["value"])}</div>' if left["name"] else f'<div class="side-none">{escape(left["value"])}</div>'
    left_panel = f'<div class="side side-vor"><div class="side-label">{escape(left["label"])}</div>{left_body}{value}</div>'

    grouped = {}
    for row in right["rows"]:
        grouped.setdefault(row["name"], []).append(row)
    body = ""
    for name, rows in grouped.items():
        lines = "<br>".join(f'{escape(r["where"].split(" · ")[0])}: {escape(r["value"])}' for r in rows)
        body += f'<div class="side-name">«{escape(name)}»</div><div class="side-lines">{lines}</div>'
    total = f'<div class="side-total">{escape(right["total"])}</div>' if right["total"] else ""
    right_panel = f'<div class="side side-act"><div class="side-label">{escape(right["label"])}</div>{body}{total}</div>'
    hint = '<div class="side-hint">Названия записаны по-разному в разных документах</div>' if left.get("names_differ") else ""
    return f'<div class="sides">{left_panel}{right_panel}</div>{hint}'


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
    """Карточка: полоса важности, название и сумма, бейджи, фраза, «в ВОР и в акте как написано», пометка, блок ИИ, источники."""
    color = SEVERITY_COLOR[c["severity"]]
    badges = badge(c["type_label"]) + badge(f"важность: {c['severity_label']}", f"badge-{c['severity']}")
    if c["ai"]:
        badges += badge("ИИ помог сопоставить", "badge-ai")
    sources = "<br>".join(escape(s) for s in c["sources"])
    note = f'<div class="issue-note">{escape(c["note"])}</div>' if c["note"] else ""
    if c["impact_value"] is not None:
        amount = f'<div class="issue-amount">{escape(c["impact_text"])}<small>возможное влияние</small></div>'
    else:
        reason = c["impact_text"].split("(", 1)[1].rstrip(")") if "(" in c["impact_text"] else "влияние не считается"
        amount = f'<div class="issue-amount">—<small>{escape(reason)}</small></div>'
    sides = sides_html(c["sides"]) if c.get("sides") else ""
    return (f'<div class="issue-card"><div class="issue-bar" style="background:{color}"></div><div class="issue-body">'
            f'<div class="issue-head"><div class="issue-title">{escape(c["title"])}</div>{amount}</div><div>{badges}</div>'
            f'<div class="issue-phrase">{escape(c["phrase"])}</div>{sides}{note}{ai_box_html(c)}'
            f'<div class="issue-src">{sources}</div></div></div>')


def cards_html(cards: list) -> str:
    return "".join(issue_card_html(c) for c in cards)


# ---------- страница обоснования ----------
def ai_line_html(text: str) -> str:
    return f'<div class="hero-note">{escape(text)}</div>'


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


def bar_chart(frame: pd.DataFrame, color: str = CHART_COLOR) -> None:
    """Горизонтальные столбцы с числами на концах (подписи типов длинные, так читаемее и на телефоне)."""
    top = float(frame["value"].max())
    base = alt.Chart(frame).encode(
        y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=260, labelFontSize=13, ticks=False, domain=False)),
        x=alt.X("value:Q", title=None, axis=None, scale=alt.Scale(domain=[0, top * 1.3 if top > 0 else 1])))
    bars = base.mark_bar(color=color, cornerRadiusEnd=3, size=22)
    labels = base.mark_text(align="left", dx=6, fontSize=13, color="#2A2723").encode(text="text:N")
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


def segmented(label: str, options: list, default: str, key: str) -> str:
    """st.segmented_control, а если версии Streamlit не хватает, горизонтальный st.radio."""
    if hasattr(st, "segmented_control"):
        picked = st.segmented_control(label, options, default=default, key=key, label_visibility="collapsed")
        return picked or default
    return st.radio(label, options, index=options.index(default), horizontal=True, key=key, label_visibility="collapsed")
