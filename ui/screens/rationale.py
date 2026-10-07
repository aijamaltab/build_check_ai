"""Страница «Обоснование»: что даёт ИИ. Цифры берутся из двух прогонов демо (без ИИ и с ИИ) и эталона синтетики."""
import streamlit as st

from src.config import load_config
from ui import components as ui
from ui.data import compact_rows, detail_rows, false_issue_ids, fmt_conf, fmt_num, quality_metrics, traffic_segments
from ui.loader import build_demo

QUALITY_NOTE = "Синтетические данные, оценка ориентировочная."
STEPS = [("Читаем Excel", "Шаблоны ВОР, сметы, договора и актов читаются по заголовкам колонок, единицы приводятся к одному виду."),
         ("Сопоставляем позиции", "Одна работа в разных документах названа по-разному. Правила сопоставляют очевидное, ИИ помогает со спорными названиями."),
         ("Считаем и показываем", "Код сравнивает объёмы, цены и даты по правилам и собирает список возможных расхождений для проверки.")]
LEAD = ("Одну и ту же работу в ведомости, смете и акте записывают по-разному. Правила сопоставляют очевидное, но не всё. "
        "Ниже видно, что меняется, когда спорные названия разбирает ИИ, а числа по-прежнему считает и проверяет код.")


ERRORS_LEAD = "ИИ ошибается реже, чем помогает, но ошибки бывают. Мы показываем их открыто"
PLAN_LINE = ("если у правил до ИИ были кандидаты для строки, отрицательный ответ ИИ («разные», «нет в ВОР») не даёт уверенного расхождения: "
             "оно помечается «ИИ не подтвердил совпадение, нужна проверка». Если кандидатов не было, поведение прежнее.")
# Статичные примеры из docs/ai_error_analysis.md (синтетические наборы, ответы Gemini из кэша)
ERROR_EXAMPLES = [
    {"set": "набор 3", "title": "Бетон: класс В25 и марка М350",
     "vor": "Устройство перекрытий из бетона В25", "act": "Плиты перекрытий монолитные М350",
     "ai": "Судья пар: «разные работы», уверенность 0,90 («бетон М350 соответствует классу В25, однако в строках указаны разные марки/классы»). "
           "Затем второй шаг: «в ВОР такой позиции нет», уверенность 0,85.",
     "result": "Раньше: ложное расхождение «нет в ВОР» высокой уверенности по двум актам (по 24 м³). Теперь у строки были кандидаты правил, поэтому "
               "расхождение низкой уверенности с пометкой «ИИ не подтвердил совпадение, нужна проверка».",
     "human": "В расхождении указаны файл, лист и строка. Специалист знает, что М350 примерно соответствует В25, и видит, что объём двух актов (24 + 24) "
              "равен плану позиции ВОР, которая в ведомости осталась невыполненной."},
    {"set": "набор 2", "title": "Шифер и асбестоцементные листы",
     "vor": "Демонтаж волнистых асбестоцементных листов кровли", "act": "Снятие шифера с крыши",
     "ai": "«В ВОР нет позиции по снятию шифера», уверенность 0,90.",
     "result": "Ложное расхождение «нет в ВОР» высокой уверенности на 1 800 м². Здесь у правил кандидатов не было, поэтому новое правило не срабатывает: "
               "поведение прежнее, ошибку ловит только человек.",
     "human": "Шифер это и есть асбестоцементные листы. Объём в акте совпадает с планом позиции о кровле, а сама позиция ВОР выполненной не показана: "
              "это видно в сверочной ведомости."},
    {"set": "набор 3", "title": "Светильники: работа или материал",
     "vor": "LED-панели светильники монтаж", "act": "Светильники панельные LED",
     "ai": "Судья пар: «разные», уверенность 0,90 («первая строка описывает материал, вторая работу по его монтажу»). Второй шаг выбрал строку-материал, "
           "уверенность 0,90; код этот выбор отклонил.",
     "result": "Два расхождения «нет в ВОР» низкой уверенности с пометкой «ИИ не подтвердил совпадение, нужна проверка»; рост цены на 23,5 % по этой позиции не проверен.",
     "human": "В акте две соседние строки: работа и материал «LED-панели»; в ВОР есть позиция монтажа светильников. Пометка низкой уверенности "
              "подсказывает открыть ведомость и сверить позицию вручную."},
]


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

    if examples:
        ui.render(ui.section_html("Как ИИ и код делят работу", "Числа ИИ не считает: он читает названия, код считает и проверяет."))
        ui.render(ui.roles_html(fmt_num(load_config()["rules"]["volume_exceeded"]["tolerance_pct"])))

    ui.render(ui.section_html("Где ИИ ошибается"))
    ui.render(f'<div class="err-lead">{ERRORS_LEAD}</div>')
    ui.render(f'<div class="plan-line"><b>Что изменено:</b> {ui.escape(PLAN_LINE)} <span class="sub">Примеры ниже показывают, как это выглядит после изменения.</span></div>')
    ui.render(ui.errors_html(ERROR_EXAMPLES))
    ui.render('<div class="note-small">Примеры из синтетических наборов 2 и 3 (data/synthetic_sets), разбор в docs/ai_error_analysis.md. '
              'Окончательное решение всегда за специалистом.</div>')
    with st.expander("Подробности: расхождения по режимам, пары названий и примеры", expanded=False):
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
            ui.render(ui.section_html("Шесть примеров из сохранённых ответов ИИ"))
            ui.render(ui.chain_html(examples))

    ui.render('<div class="app-footer">Прототип. Данные синтетические. Результат требует проверки специалистом.</div>')
