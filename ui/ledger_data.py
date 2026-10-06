"""Данные «Сверочной ведомости»: строка = позиция из position_status. Без Streamlit и без SQL, только подготовка к показу.

Расхождения и цвета берутся из готовых issues и position_status, по правилам здесь ничего не пересчитывается: ячейка подсвечивается,
если у позиции есть issue этого типа или светофор жёлтый. Цена по смете и по акту нужна только для показа."""
import pandas as pd

from src.config import load_config
from ui.data import (EMPTY, LOW_CONFIDENCE_NOTE, SEVERITY_RU, SOURCE_ROLE, STATUS_SINGULAR, TYPE_ORDER, TYPE_RU, _clean, fmt_conf, fmt_num,
                     fmt_pct)



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
            "dp": EMPTY if dprice is None or pd.isna(dprice) else ("0,0%" if abs(dprice) < 0.05 else fmt_pct(dprice)),
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
