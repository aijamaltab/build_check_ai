"""Страница «Обоснование»: что даёт ИИ. Цифры берутся из двух прогонов демо (без ИИ и с ИИ) и эталона синтетики."""
import streamlit as st

from src.config import load_config
from ui import components as ui
from ui.data import compact_rows, detail_rows, false_issue_ids, fmt_conf, fmt_num, quality_metrics, traffic_segments
from ui.loader import build_demo
from ui.screens.files import render_files

QUALITY_NOTE = "Синтетические данные, оценка ориентировочная."
STEPS = [("Читаем Excel", "Шаблоны ВОР, сметы, договора и актов читаются по заголовкам колонок, единицы приводятся к одному виду."),
         ("Сопоставляем позиции", "Одна работа в разных документах названа по-разному. Правила сопоставляют очевидное, ИИ помогает со спорными названиями."),
         ("Считаем и показываем", "Код сравнивает объёмы, цены и даты по правилам и собирает список возможных расхождений для проверки.")]
LEAD = ("Одну и ту же работу в ведомости, смете и акте записывают по-разному. Правила сопоставляют очевидное, но не всё. "
        "Ниже видно, что меняется, когда спорные названия разбирает ИИ, а числа по-прежнему считает и проверяет код.")


def render() -> None:
    ui.render('<div class="hero"><div class="hero-title">Зачем здесь ИИ</div>'
              f'<div class="hero-lead">{LEAD}</div></div>')
    try:
        with_ai, without_ai = build_demo("llm"), build_demo("rules_only")
    except Exception:  # noqa: BLE001
        st.error("Не удалось собрать результат из демо-проекта. Обновите страницу.")
        return
    if with_ai["summary"]["mode"] != "llm":
        ui.render(ui.banner_html(with_ai["summary"]["banner"] or "ИИ-режим недоступен, сравнение невозможно"))
        return

    ui.render(ui.section_html("Как это работает"))
    ui.render(ui.trio_html(STEPS))

    examples = with_ai["ai_examples"]
    pair = next((e for e in examples if e["kind"] == "pair_accepted"), None)
    if pair:
        ui.render(ui.claim_html(f"В ВОР: «{pair['vor']}». В акте: «{pair['doc']}». Это одна работа, но названия разные: правила по схожести "
                                f"сомневаются, ИИ уверенно подтверждает."))

    ui.render(ui.section_html("Без ИИ и с ИИ", "Те же девять файлов, два режима. Эталон: заложенные расхождения синтетического проекта."))
    ui.render(ui.compare_html(detail_rows(without_ai, with_ai), QUALITY_NOTE))
    ui.render(ui.section_html("Светофор по позициям в двух режимах", "Без ИИ часть позиций ложно жёлтая: строки акта остались без пары и не попали в факт."))
    ui.render('<div class="side-label">Без ИИ</div>' + ui.traffic_html(traffic_segments(without_ai["summary"])))
    ui.render('<div class="side-label" style="margin-top:10px">С ИИ</div>' + ui.traffic_html(traffic_segments(with_ai["summary"])))
    a, b = quality_metrics(without_ai["issues"]), quality_metrics(with_ai["issues"])
    ui.render(ui.claim_html(f"Без ИИ найдено {a['found']} из {a['gt_total']} заложенных расхождений и {a['false']} ложных. "
                            f"С ИИ найдено {b['found']} из {b['gt_total']} и {b['false']} ложное: строки, у которых пара в ВОР есть, "
                            f"перестали попадать в «нет в ВОР»."))

    false_without, false_with = false_issue_ids(without_ai["issues"]), false_issue_ids(with_ai["issues"])
    ui.render(ui.section_html("Что показывает каждый режим", "В колонке «По эталону» видно, какие расхождения ложные."))
    tab_without, tab_with = st.tabs([f"Без ИИ ({len(without_ai['issues'])})", f"С ИИ ({len(with_ai['issues'])})"])
    with tab_without:
        ui.render(ui.html_table(compact_rows(without_ai["issues"], without_ai["positions"], false_without), mark_false=True))
    with tab_with:
        ui.render(ui.html_table(compact_rows(with_ai["issues"], with_ai["positions"], false_with), mark_false=True))

    ui.render(ui.section_html("Что сопоставил ИИ", "Пары названий, которые правила не склеили, а ИИ сопоставил. Код проверил единицу и числа."))
    import pandas as pd
    pairs = pd.DataFrame([{"Документ": {"act": "Акт", "estimate": "Смета"}.get(p["doc_type"], "Док."), "Как написано в документе": p["doc"],
                           "Как написано в ВОР": p["vor"], "Уверенность": fmt_conf(p["confidence"]), "Причина (ответ ИИ)": p["reason"]}
                          for p in with_ai["ai_pairs_all"]])
    ui.render(ui.html_table(pairs))

    if examples:
        ui.render(ui.section_html("Как ИИ и код делят работу", "Числа ИИ не считает. Ниже шесть примеров из сохранённых ответов ИИ."))
        ui.render(ui.roles_html(fmt_num(load_config()["rules"]["volume_exceeded"]["tolerance_pct"])))
        ui.render(ui.chain_html(examples))

    wrong = [r for _, r in compact_rows(with_ai["issues"], with_ai["positions"], false_with).iterrows() if r["По эталону"].startswith("ложное")]
    ui.render(ui.section_html("Где ИИ ошибается", "Поэтому окончательное решение всегда за специалистом."))
    if wrong:
        false_rows = with_ai["issues"][with_ai["issues"]["issue_id"].isin(false_with)]
        none = next((x for x in false_rows["ai_none"] if x), None)
        conf = f", уверенность {fmt_conf(none['confidence'])}" if none else ""
        parts = [f"«{r['Работа']}» ({r['Влияние']}{conf})" for r in wrong]
        names = "; ".join(parts)
        ui.render(f'<div class="errbox">С ИИ осталось {len(wrong)} ложное расхождение: {ui.escape(names)}. ИИ не нашёл в ВОР пару, хотя она есть. '
                  'Человек ловит это при проверке: расхождение помечено «ИИ не нашёл пару в ВОР, требует проверки», рядом указан файл, лист и строка, '
                  'специалист открывает ведомость и видит, что позиция там есть.</div>')
    else:
        ui.render(ui.claim_html("В этом прогоне ложных расхождений с ИИ нет, но на других документах они возможны."))
    with st.expander("Исходные файлы демо", expanded=False):
        render_files(with_ai)
    ui.render('<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>')
