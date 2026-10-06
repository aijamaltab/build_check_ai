"""Данные «Сверочной ведомости»: строка = позиция из position_status. Без Streamlit и без SQL, только подготовка к показу.

Расхождения и цвета берутся из готовых issues и position_status, по правилам здесь ничего не пересчитывается: ячейка подсвечивается,
если у позиции есть issue этого типа или светофор жёлтый. Цена по смете и по акту нужна только для показа."""
import pandas as pd

from src.config import load_config
from ui.data import (EMPTY, LOW_CONFIDENCE_NOTE, SEVERITY_RU, SOURCE_ROLE, STATUS_SINGULAR, TYPE_ORDER, TYPE_RU, _clean, build_cards, fmt_conf,
                     fmt_date, fmt_num, fmt_pct, quality_metrics, sort_issues)



def _where(role: str, file, sheet, row) -> str:
    return f"{role} · {file} · лист «{sheet}» · строка {int(row)}"


def _src_rows(part: pd.DataFrame, role: str, unit: str, markers) -> list:
    out = []
    for x in part.sort_values(["source_file", "source_row"]).itertuples():
        price = None if pd.isna(x.unit_price) else f"{fmt_num(x.unit_price)} сом за {unit}"
        out.append({"role": role, "file": x.source_file, "where": _where(role, x.source_file, x.source_sheet, x.source_row),
                    "name": _clean(x.work_name_raw, markers), "qty": f"{fmt_num(x.quantity)} {unit}".strip(), "price": price})
    return out


def _ai_text(pairs: list) -> str:
    if not pairs:
        return ""
    conf = sorted(p["confidence"] for p in pairs if p["confidence"] is not None)
    if not conf:
        return "ИИ сопоставил названия"
    span = fmt_conf(conf[0]) if conf[0] == conf[-1] else f"{fmt_conf(conf[0])}–{fmt_conf(conf[-1])}"
    return f"ИИ сопоставил названия (уверенность {span})"


def _weighted_price(part: pd.DataFrame):
    priced = part[part["unit_price"].notna()]
    if priced.empty:
        return None
    qty = priced["quantity"].fillna(0)
    return float((priced["unit_price"] * qty).sum() / qty.sum()) if qty.sum() > 0 else float(priced["unit_price"].mean())


def _tip(title: str, facts: list, sources: list, ai: str, issue_rows=None) -> dict:
    impact = None
    if issue_rows is not None and not issue_rows.empty and issue_rows["impact_som"].notna().any():
        impact = f"{fmt_num(issue_rows['impact_som'].sum())} сом"
    return {"title": title, "facts": facts, "sources": [x["where"] for x in sources], "impact": impact, "ai": ai}


def build_ledger(results: dict) -> dict:
    """-> {rows, doc_issues (расхождения без позиции, например акт после срока), units, total}.

    Цена по смете и по акту: при расхождении по цене значения из issue (смета и акт, давший расхождение), иначе средневзвешенная по
    количеству цена строк items с этим ключом. Колонка статуса: цвет, слово и стрелка (up: факт выше плана или позиции нет в ВОР,
    down: ниже плана), чтобы смысл не держался только на цвете."""
    cfg = load_config()
    rules = cfg["rules"]
    over, under = rules["volume_exceeded"]["tolerance_pct"], rules["position_status"]["green_under_tolerance_pct"]
    markers = cfg["synonyms"].get("strip_markers", [])
    positions, issues, items = results["positions"], results["issues"], results["items"]
    ai_by_key = results.get("ai_by_key", {})
    rows, linked = [], set()
    for number, p in enumerate(positions.itertuples(), 1):
        unit = p.unit_label or ""
        part = items[items["work_key"] == p.work_key]
        mine = issues[issues["work_key"] == p.work_key] if not issues.empty else issues
        by_type = {t: mine[mine["issue_type"] == t] for t in TYPE_ORDER}
        vol, price_issue, missing = by_type["volume_exceeded"], by_type["price_increase"], by_type["missing_in_vor"]
        linked.update(int(i) for i in mine["issue_id"])
        pct = None if pd.isna(p.pct) else float(p.pct)
        vor_src = _src_rows(part[part["doc_type"] == "vor"], "ВОР", unit, markers)
        est_src = _src_rows(part[part["doc_type"] == "estimate"], "Смета", unit, markers)
        act_src = _src_rows(part[part["doc_type"] == "act"], "Акт", unit, markers)
        est_price = _weighted_price(part[part["doc_type"] == "estimate"])
        act_price = _weighted_price(part[part["doc_type"] == "act"])
        dprice = None
        if not price_issue.empty:
            first = price_issue.iloc[0]
            est_price, act_price, dprice = first["expected"], first["actual"], first["delta_pct"]
        elif est_price and act_price is not None:
            dprice = (act_price - est_price) / est_price * 100
        ai = _ai_text(ai_by_key.get(p.work_key, []))
        plan_text, fact_text = f"{fmt_num(p.plan_qty)} {unit}".strip(), f"{fmt_num(p.fact_qty)} {unit}".strip()
        hl, tips = {}, {}
        if not vol.empty or (pct is not None and pct > 100 + over):
            dev = fmt_pct(vol.iloc[0]["delta_pct"]) if not vol.empty else fmt_pct(pct - 100)
            facts = [f"ВОР: {plan_text}", f"Акты: {fact_text}", f"Отклонение: {dev} (допуск {fmt_num(over)} %)"]
            hl["fact"] = hl["pct"] = "red"
            tips["fact"] = tips["pct"] = _tip("Превышение объёма", facts, vor_src + act_src, ai, vol)
        elif p.status == "yellow" and pct is not None:
            facts = [f"ВОР: {plan_text}", f"Акты: {fact_text}", f"Выполнено {fmt_num(round(pct, 1))} %: ниже плана более чем на {fmt_num(under)} %"]
            if p.review_rows:
                facts.append(f"Строк актов без пары, которые могут относиться к позиции: {int(p.review_rows)}")
            hl["fact"] = hl["pct"] = "yellow"
            tips["fact"] = tips["pct"] = _tip("Выполнено меньше плана", facts, vor_src + act_src, ai)
        if not price_issue.empty:
            facts = [f"Смета: {fmt_num(est_price)} сом за {unit}", f"Акт: {fmt_num(act_price)} сом за {unit}", f"Отклонение: {fmt_pct(dprice)}"]
            culprit = set(price_issue.iloc[0]["sources"])
            shown_acts = [x for x in act_src if x["where"] in culprit] or act_src
            for col in ("est", "actp", "dp"):
                hl[col] = "red"
                tips[col] = _tip("Рост цены", facts, est_src + shown_acts, ai, price_issue)
        if not missing.empty:
            note = missing.iloc[0]["review_note"]
            facts = [f"В акте: {fact_text}", "В ВОР пары не найдено"] + ([note] if isinstance(note, str) and note else [])
            for col in ("name", "fact"):
                hl[col] = "red"
                tips[col] = _tip("Нет в ВОР", facts, act_src, ai, missing)
        if p.status != "green":
            reasons = [TYPE_RU[t] for t in TYPE_ORDER if not by_type[t].empty]
            if p.status == "yellow":
                reasons.append("Выполнено меньше плана")
            hl["status"] = p.status
            tips["status"] = _tip("Статус: " + STATUS_SINGULAR[p.status].lower(), reasons or ["Факт по актам отличается от плана"], [], ai, mine)
        if pd.isna(p.plan_qty) or (pct is not None and pct > 100 + over):
            arrow = "up"
        elif pct is not None and pct < 100 - under:
            arrow = "down"
        else:
            arrow = ""
        rows.append({
            "n": number, "key": p.work_key, "name": p.name, "unit": unit, "plan": fmt_num(p.plan_qty), "fact": fmt_num(p.fact_qty),
            "pct": EMPTY if pct is None else fmt_num(round(pct, 1)), "est": fmt_num(est_price), "actp": fmt_num(act_price),
            "dp": fmt_pct(dprice) if not price_issue.empty and dprice is not None and not pd.isna(dprice) else EMPTY,
            "status": p.status, "status_ru": STATUS_SINGULAR[p.status], "arrow": arrow, "hl": hl, "tips": tips, "has_issue": not mine.empty,
            "sources": {"ВОР": vor_src, "Смета": est_src, "Акты": act_src},
            "issues": [{"type": TYPE_RU[r.issue_type], "severity": SEVERITY_RU[r.severity], "text": r.explanation,
                        "impact": None if pd.isna(r.impact_som) else f"{fmt_num(r.impact_som)} сом",
                        "note": LOW_CONFIDENCE_NOTE if r.confidence == "low" else "", "sources": list(r.sources)} for r in mine.itertuples()],
            "ai": [{"doc": f"{SOURCE_ROLE.get(a['doc_type'], 'Док.')}: «{a['doc']}»", "vor": a["vor"], "confidence": fmt_conf(a["confidence"]),
                    "reason": a["reason"]} for a in ai_by_key.get(p.work_key, [])],
            "files": sorted({x["file"] for x in vor_src + est_src + act_src}),
        })
    loose = issues[~issues["issue_id"].isin(linked)] if not issues.empty else issues
    doc_issues = [{"type": TYPE_RU[r.issue_type], "severity": SEVERITY_RU[r.severity], "text": r.explanation, "sources": list(r.sources)}
                  for r in loose.itertuples()]
    return {"rows": rows, "doc_issues": doc_issues, "units": sorted({r["unit"] for r in rows if r["unit"]}), "total": len(rows)}


def issue_what(r, over: float, price_tol: float) -> str:
    """Одна фраза «что не сходится» с числами из issue: «В актах 98 м3, в ВОР 85 м3, на 15,3 % больше при допуске 5 %»."""
    unit = f" {r['unit']}" if r["unit"] else ""
    pct = "" if pd.isna(r["delta_pct"]) else fmt_num(round(abs(float(r["delta_pct"])), 1))
    kind = r["issue_type"]
    if kind == "volume_exceeded":
        return f"В актах {fmt_num(r['actual'])}{unit}, в ВОР {fmt_num(r['expected'])}{unit}, на {pct} % больше при допуске {fmt_num(over)} %"
    if kind == "price_increase":
        if pd.isna(r["expected"]):
            return f"Цена в акте {fmt_num(r['actual'])} сом за{unit or ' ед.'}; цены в смете для сравнения нет"
        return f"Цена в акте {fmt_num(r['actual'])} сом, в смете {fmt_num(r['expected'])} сом (за{unit or ' ед.'}), на {pct} % выше при допуске {fmt_num(price_tol)} %"
    if kind == "missing_in_vor":
        return f"В актах {fmt_num(r['actual'])}{unit}, в ВОР такой позиции не найдено"
    return f"Акт датирован {fmt_date(r['actual_text'])}, срок договора {fmt_date(r['expected_text'])}: позже срока на {fmt_num(r['actual'])} дн."


def build_issue_rows(results: dict) -> dict:
    """Строки таблицы «Возможные расхождения» (режим issues компонента ui/ledger.py): только расхождения, по важности и влиянию.

    У каждой строки одна подсказка с полными деталями (для всех колонок): фраза, объяснение из issues, влияние, источники, метка ИИ."""
    rules = load_config()["rules"]
    over, price_tol = rules["volume_exceeded"]["tolerance_pct"], rules["price_increase"]["tolerance_pct"]
    issues = sort_issues(results["issues"])
    cards = build_cards(issues, results["positions"])
    ai_by_key = results.get("ai_by_key", {})
    columns = ["n", "type", "name", "text", "impact", "where"]
    rows = []
    for number, ((_, r), c) in enumerate(zip(issues.iterrows(), cards), 1):
        what = issue_what(r, over, price_tol)
        facts = [what, str(r["explanation"])] + ([c["note"]] if c["note"] else [])
        ai = _ai_text(ai_by_key.get(r["work_key"], [])) if c["ai"] else ""
        impact = EMPTY if c["impact_value"] is None else fmt_num(c["impact_value"])
        tip = {"title": f"{c['type_label']} · важность: {c['severity_label']}", "facts": facts, "sources": list(c["sources"]),
               "impact": None if c["impact_value"] is None else f"{impact} сом", "ai": ai}
        rows.append({"n": number, "issue_id": c["issue_id"], "type": c["type_label"], "type_sub": f"важность: {c['severity_label']}",
                     "name": c["title"], "text": what, "impact": impact, "where": list(c["sources"]), "ai_badge": bool(ai),
                     "hl": {}, "tips": {k: tip for k in columns}})
    return {"rows": rows, "total": len(rows)}


def summary_points(results: dict, rules_results: dict) -> list:
    """Итоги сверки текстом, только из данных: число и типы расхождений, влияние, что проверить первыми, сравнение с режимом без ИИ.

    Числа берутся из run_summary (results['summary']), issues и quality_metrics (scripts/evaluate.py по эталону синтетики)."""
    summary, issues = results["summary"], results["issues"]
    if issues.empty:
        return ["Возможных расхождений не найдено."]
    linked = issues[issues["work_key"].notna() & (issues["work_key"] != "")]
    n_pos, n_doc = linked["work_key"].nunique(), len(issues) - len(linked)
    where = f"по {n_pos} позициям" + (f" и {n_doc} документам (акт после срока)" if n_doc else "")
    counts = issues["issue_type"].value_counts()
    top_type = max(TYPE_ORDER, key=lambda t: counts.get(t, 0))
    by_impact = issues[issues["impact_som"].notna()].sort_values(["impact_som", "issue_id"], ascending=[False, True]).head(3)
    first = build_cards(by_impact, results["positions"])
    a, b = quality_metrics(rules_results["issues"]), quality_metrics(issues)
    return [
        f"Найдено {len(issues)} возможных расхождений {where}.",
        f"Чаще всего: {TYPE_RU[top_type].lower()} ({int(counts.get(top_type, 0))}).",
        f"Возможное влияние на бюджет: {fmt_num(summary['impact_som'])} сом (оценка размера расхождений, не вывод о потерях).",
        "Проверить первыми: " + "; ".join(f"{c['title']} ({c['impact_text']})" for c in first) + ".",
        f"Без ИИ было бы {a['issues']} расхождений, из них {a['false']} ложных; с ИИ {b['issues']}, из них ложных {b['false']}.",
    ]
