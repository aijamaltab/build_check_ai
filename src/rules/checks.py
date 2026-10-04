"""Четыре проверки расхождений по сопоставленным данным (docs/synthetic_spec.md §5, §6, §7). Без ИИ и без сети.

Все числа считает код (LLM чисел не считает), пороги и тексты берутся из config/rules.yaml.
  volume_exceeded: накопительный факт по актам (по дате акта) больше объёма ВОР с допуском;
  price_increase:  средневзвешенная цена по ключу в одном акте (сумма / количество) выше сметной с допуском;
                   при несовпадении валют проверка не выполняется («не сопоставимо»);
  missing_in_vor:  строка акта в состоянии absent (ambiguous в issues не попадает);
  late_act:        дата акта позже срока договора.
Контракт §7: в issues нет колонки листа и влияния на бюджет, они лежат в staging_issues_ext (читает view issues_view).
"""
import datetime as dt
from dataclasses import dataclass, field

STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS staging_issues_ext (
    issue_id       INTEGER PRIMARY KEY REFERENCES issues(issue_id),
    source_sheet   TEXT NOT NULL,
    impact_som     REAL,
    impact_note    TEXT,
    confidence     TEXT,            -- high | low (у missing_in_vor: подтвердил ли ИИ «в ВОР нет»), у остальных high
    review_note    TEXT,
    expected_text  TEXT,
    actual_text    TEXT,
    unit           TEXT,
    mode           TEXT
);
"""

EPS = 9      # знаков при сравнении процентов с допуском: граница допуска входит в допуск


def fmt(x, digits=2) -> str:
    """Число для текста: пробел как разделитель тысяч, без хвоста нулей."""
    if x is None:
        return "—"
    text = f"{float(x):,.{digits}f}".replace(",", " ")
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return text.replace(".", ",")                         # по-русски десятичная запятая


@dataclass
class ChecksResult:
    counts: dict = field(default_factory=dict)          # issue_type -> число расхождений
    incomparable_rows: int = 0                          # строки, у которых проверка цены не выполнена из-за валют
    impact_total: float = 0.0
    n_issues: int = 0


def init_issue_tables(conn) -> None:
    conn.executescript(STAGING_SCHEMA)
    conn.commit()


def clear_issues(conn, project_id: str, cfg: dict) -> None:
    conn.execute("DELETE FROM staging_issues_ext WHERE issue_id IN (SELECT issue_id FROM issues WHERE project_id = ?)", (project_id,))
    conn.execute("DELETE FROM issues WHERE project_id = ?", (project_id,))
    docs = "SELECT doc_id FROM documents WHERE project_id = ?"
    conn.execute(f"DELETE FROM dq_checks WHERE check_name = ? AND doc_id IN ({docs})",
                 (cfg["rules"]["currency"]["mismatch_dq_check"], project_id))


class _Data:
    """Чтение групп и их строк из staging_match_* (результат matching)."""

    def __init__(self, conn, project_id):
        self.conn, self.project_id = conn, project_id

    def groups(self, where, args=()):
        return self.conn.execute(
            "SELECT g.*, i.source_file, i.source_sheet, i.source_row, i.work_name_raw, i.doc_date FROM staging_match_groups g "
            "JOIN items i ON i.item_id = g.first_item_id WHERE g.project_id = ? AND " + where, (self.project_id, *args)).fetchall()

    def rows(self, group_id):
        return self.conn.execute(
            "SELECT i.item_id, i.source_row, i.quantity, i.amount, i.unit_price, r.counted, e.currency, e.price_is_formula "
            "FROM staging_match_rows r JOIN items i ON i.item_id = r.item_id JOIN staging_items_ext e ON e.item_id = i.item_id "
            "WHERE r.group_id = ? ORDER BY i.source_row", (group_id,)).fetchall()

    def estimate_price(self, vor_group_id):
        """Средневзвешенная цена сметы по ключу ВОР: сумма / количество по строкам сметы, привязанным к этой позиции.
        -> (цена, валюта) или (None, None)."""
        q = s = 0.0
        currency = None
        for g in self.groups("g.doc_type = 'estimate' AND g.status = 'matched' AND g.matched_group_id = ?", (vor_group_id,)):
            for r in self.rows(g["group_id"]):
                if r["counted"] and r["amount"] is not None and r["quantity"]:
                    q, s, currency = q + r["quantity"], s + r["amount"], r["currency"]
        return (s / q, currency) if q > 0 else (None, None)


def _add_issue(conn, project_id, mode, issue_type, work_key, expected, actual, delta, delta_pct, severity, src, explanation,
               impact=None, impact_note=None, confidence="high", review_note=None, expected_text=None, actual_text=None, unit=None):
    issue_id = conn.execute(
        "INSERT INTO issues (project_id, work_key, issue_type, expected, actual, delta, delta_pct, severity, source_file, source_row,"
        " explanation) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, work_key, issue_type, expected, actual, delta, delta_pct, severity, src[0], src[2], explanation)).lastrowid
    conn.execute("INSERT INTO staging_issues_ext (issue_id, source_sheet, impact_som, impact_note, confidence, review_note, "
                 "expected_text, actual_text, unit, mode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (issue_id, src[1], None if impact is None else round(impact, 2), impact_note, confidence, review_note,
                  expected_text, actual_text, unit, mode))
    return issue_id


def _severity(delta_pct, high_pct, cfg):
    return "high" if round(delta_pct, EPS) >= high_pct else cfg["rules"]["issues"]["severity_default"]


def run_checks(conn, cfg: dict, project_id: str, mode: str = "rules_only") -> ChecksResult:
    """Пересчитывает issues проекта с нуля (повторный запуск не дублирует). mode: фактический режим прогона."""
    init_issue_tables(conn)
    clear_issues(conn, project_id, cfg)
    rules, data = cfg["rules"], _Data(conn, project_id)
    texts, labels = rules["issues"]["explanations"], rules["issues"]["unit_labels"]
    result = ChecksResult(counts={"volume_exceeded": 0, "price_increase": 0, "missing_in_vor": 0, "late_act": 0})
    default_currency = rules["currency"]["default"]
    vor_groups = {g["group_id"]: g for g in data.groups("g.doc_type = 'vor'")}
    act_groups = data.groups("g.doc_type = 'act' AND g.status = 'matched'")
    act_groups.sort(key=lambda g: (g["doc_date"] or "", g["source_file"], g["source_row"]))

    # ---- (а) объём: накопительно по актам в порядке дат ----
    tol, high = rules["volume_exceeded"]["tolerance_pct"], rules["volume_exceeded"]["high_pct"]
    for v in vor_groups.values():
        plan = v["qty_sum"]
        mine = [a for a in act_groups if a["matched_group_id"] == v["group_id"]]
        if not mine or not plan or plan <= 0:
            continue
        cum, hit = 0.0, None
        for a in mine:
            cum += a["qty_sum"]
            if hit is None and round((cum - plan) / plan * 100, EPS) > tol:
                hit = a
        delta_pct = (cum - plan) / plan * 100
        if hit is None:
            continue
        unit = labels.get(v["unit_norm"], v["unit_norm"] or "")
        price, _ = data.estimate_price(v["group_id"])
        impact = (cum - plan) * price if price is not None else None
        text = texts["volume_exceeded"].format(actual=fmt(cum), expected=fmt(plan), unit=unit, delta_pct=fmt(delta_pct, 1), tolerance=fmt(tol))
        extra = [r for r in data.rows(hit["group_id"]) if r["source_row"] != hit["source_row"]]
        if extra:
            text += " " + texts["other_rows"].format(rows=", ".join(str(r["source_row"]) for r in extra))
        if any(r["price_is_formula"] for a in mine for r in data.rows(a["group_id"])):
            text += " " + rules["volume_exceeded"]["explanation_if_price_is_formula"].capitalize() + "."
        _add_issue(conn, project_id, mode, "volume_exceeded", v["final_work_key"], plan, cum, cum - plan, delta_pct,
                   _severity(delta_pct, high, cfg), (hit["source_file"], hit["source_sheet"], hit["source_row"]), text,
                   impact, None if impact is not None else rules["issues"]["no_estimate_price_note"], unit=unit)
        result.counts["volume_exceeded"] += 1

    # ---- (б) цена: средневзвешенная по ключу в одном акте против сметы ----
    tol_p, high_p = rules["price_increase"]["tolerance_pct"], rules["price_increase"]["high_pct"]
    mismatch_docs = {}
    for a in act_groups:
        used = [r for r in data.rows(a["group_id"]) if r["counted"] and r["amount"] is not None and r["quantity"]]
        if not used:
            continue                                            # у материалов и мусора цен в актах нет
        est_price, est_currency = data.estimate_price(a["matched_group_id"])
        if est_price is None:
            continue
        currency = used[0]["currency"]
        if currency != est_currency:                            # валюты не конвертируем: «не сопоставимо»
            result.incomparable_rows += len(used)
            mismatch_docs.setdefault(a["doc_id"], []).append(a["source_row"])
            continue
        q = sum(r["quantity"] for r in used)
        price = sum(r["amount"] for r in used) / q
        delta_pct = (price - est_price) / est_price * 100
        if round(delta_pct, EPS) <= tol_p:
            continue
        v = vor_groups[a["matched_group_id"]]
        unit = labels.get(v["unit_norm"], v["unit_norm"] or "")
        text = texts["price_increase"].format(actual=f"{fmt(price)} {currency}", expected=f"{fmt(est_price)} {est_currency}", unit=unit,
                                              delta_pct=fmt(delta_pct, 1), tolerance=fmt(tol_p))
        if len(used) > 1:
            text += " " + texts["other_rows"].format(rows=", ".join(str(r["source_row"]) for r in used[1:]))
        if any(r["price_is_formula"] for r in used):
            text += " " + rules["price_increase"]["formula_price_note"].capitalize() + "."
        _add_issue(conn, project_id, mode, "price_increase", v["final_work_key"], est_price, price, price - est_price, delta_pct,
                   _severity(delta_pct, high_p, cfg), (a["source_file"], a["source_sheet"], a["source_row"]), text,
                   (price - est_price) * q, unit=unit)
        result.counts["price_increase"] += 1
    for doc_id, nums in mismatch_docs.items():
        conn.execute("INSERT INTO dq_checks (doc_id, check_name, passed, details) VALUES (?,?,?,?)",
                     (doc_id, rules["currency"]["mismatch_dq_check"], 0,
                      rules["issues"]["currency_mismatch_note"] + "; строки " + ", ".join(map(str, nums))))

    # ---- (в) позиция в акте без пары в ВОР: только absent ----
    mv = rules["issues"]["missing_in_vor"]
    min_conf = rules["llm"]["min_confidence"]
    for g in data.groups("g.doc_type = 'act' AND g.status = 'absent'"):
        rows = [r for r in data.rows(g["group_id"]) if r["counted"]]
        confirmed = mode == "llm" and conn.execute(
            "SELECT 1 FROM staging_llm_row_decisions WHERE group_id = ? AND outcome = 'none' AND confidence >= ?",
            (g["group_id"], min_conf)).fetchone() is not None
        amounts = [r["amount"] if r["amount"] is not None else (r["quantity"] * r["unit_price"] if r["unit_price"] is not None else None)
                   for r in rows]
        same_currency = all(r["currency"] == default_currency for r in rows)
        impact = sum(a for a in amounts if a is not None) if same_currency and any(a is not None for a in amounts) else None
        unit = labels.get(g["unit_norm"], g["unit_norm"] or "")
        text = texts["missing_in_vor"].format(name=g["work_name_raw"], actual=fmt(g["qty_sum"]), unit=unit)
        note = mv["confirmed_note"] if confirmed else mv["low_confidence_note"]
        if not confirmed and mode == "rules_only":
            note += " " + rules["matching"]["rules_only_explanation"] + "."
        _add_issue(conn, project_id, mode, "missing_in_vor", g["final_work_key"], 0, g["qty_sum"], g["qty_sum"], None,
                   mv["severity_confirmed"] if confirmed else mv["severity_unconfirmed"],
                   (g["source_file"], g["source_sheet"], g["source_row"]), text + " " + note, impact,
                   None if impact is not None else rules["issues"]["no_estimate_price_note"],
                   confidence="high" if confirmed else "low", review_note=note, unit=unit)
        result.counts["missing_in_vor"] += 1

    # ---- (г) акт позже срока договора ----
    deadline = conn.execute("SELECT doc_date FROM items WHERE project_id = ? AND doc_type = 'contract' AND doc_date IS NOT NULL LIMIT 1",
                            (project_id,)).fetchone()
    if deadline:
        grace = rules["late_act"]["grace_days"]
        d_deadline = dt.date.fromisoformat(deadline[0])
        acts = conn.execute(
            "SELECT i.doc_id, i.source_file, i.source_sheet, MIN(i.source_row) first_row, i.doc_date, s.date_source_row FROM items i "
            "JOIN staging_documents_ext s ON s.doc_id = i.doc_id WHERE i.project_id = ? AND i.doc_type = 'act' AND i.doc_date IS NOT NULL "
            "GROUP BY i.doc_id ORDER BY i.doc_date, i.source_file", (project_id,)).fetchall()
        for a in acts:
            days = (dt.date.fromisoformat(a["doc_date"]) - d_deadline).days
            if days <= grace:
                continue
            row = a["date_source_row"] or a["first_row"]
            text = texts["late_act"].format(actual_date=a["doc_date"], expected_date=deadline[0], days=days)
            _add_issue(conn, project_id, mode, "late_act", None, grace, days, days, None, rules["late_act"]["severity"],
                       (a["source_file"], a["source_sheet"], row), text, None, "не считается", expected_text=deadline[0],
                       actual_text=a["doc_date"], unit="дн.")
            result.counts["late_act"] += 1
    result.n_issues = sum(result.counts.values())
    result.impact_total = conn.execute(
        "SELECT COALESCE(SUM(e.impact_som), 0) FROM staging_issues_ext e JOIN issues i USING(issue_id) WHERE i.project_id = ?",
        (project_id,)).fetchone()[0]
    conn.commit()
    return result
