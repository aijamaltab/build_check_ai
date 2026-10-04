#!/usr/bin/env python
"""Оценка ответов Gemini по эталону генератора, только по кэшу (API не вызывается, ключ не нужен).

  python scripts/eval_pairs.py [--source data/synthetic] [--threshold 90]

Прогоняет run_pipeline в режиме llm с настоящим GeminiPairJudge в режиме «только кэш»: пары, которых нет в кэше, остаются без
ответа. Каждая пара, ушедшая судье, сравнивается с эталоном (журнал генератора): матрица ошибок по ответам модели, список
расхождений, работа проверки кода, затем метрики evaluate.py для режимов «без ИИ со словарём», «настоящий судья по кэшу»
и «потолок» (фейковые судьи по эталону: это не оценка модели), причины ненайденных GT и ложных missing_in_vor.
Данные синтетические, словарь составлен по тем же названиям: цифры оптимистичны. Файлы проекта и данные не меняются.
"""
import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate as ev  # noqa: E402
import verify_matching as vm  # noqa: E402
from src.config import load_config  # noqa: E402
from src.llm import GeminiPairJudge, LlmClient  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

CHECK_PREFIX = "отклонено проверкой"


class RecordingJudge:
    """Обёртка над настоящим судьёй: запоминает каждую пару, сырой ответ модели из кэша и итог после проверок кода."""
    available = True

    def __init__(self, inner: GeminiPairJudge):
        self.inner, self.client, self.records, self._raw = inner, inner.client, [], None
        original_get = self.client.cache.get

        def get(key):
            record = original_get(key)
            self._raw = record["answer"] if record else None
            return record

        self.client.cache.get = get

    stats = property(lambda self: self.inner.stats)
    stop_reason = property(lambda self: self.inner.stop_reason)
    warnings = property(lambda self: self.inner.warnings)

    def judge_pair(self, a, b, context):
        self._raw = None
        result = self.inner.judge_pair(a, b, context)
        self.records.append({"a": a, "b": b, "raw": self._raw, "result": result})
        return result


def outcome(record) -> str:
    """Что случилось с парой: answered / rejected_by_check / low_confidence / no_answer."""
    if record["raw"] is None:
        return "no_answer"
    result = record["result"]
    if result is None:
        return "low_confidence"
    if result["reason"].startswith(CHECK_PREFIX):
        return "rejected_by_check"
    return "answered"


def pair_truth(truth, record) -> bool:
    a, b = record["a"], record["b"]
    return truth.get((a["file"], a["row"])) == truth.get((b["file"], b["row"]))


def confusion(records, truth) -> dict:
    """Матрица ошибок по сырым ответам модели (до проверок кода) для пар, на которые ответ есть."""
    m = {"tp": 0, "tn": 0, "fp": 0, "fn": 0, "diffs": [], "unanswered": 0}
    for r in records:
        if r["raw"] is None:
            m["unanswered"] += 1
            continue
        same, model_same = pair_truth(truth, r), r["raw"]["same_work"]
        key = {(True, True): "tp", (False, False): "tn", (False, True): "fp", (True, False): "fn"}[(same, model_same)]
        m[key] += 1
        if same != model_same:
            m["diffs"].append({"kind": "ложное «одна работа»" if model_same else "пропущенное «одна работа»",
                               "a": r["a"].get("name_raw"), "b": r["b"].get("name_raw"), "model": model_same,
                               "confidence": r["raw"]["confidence"], "reason": r["raw"]["reason"], "truth": same})
    answered = m["tp"] + m["tn"] + m["fp"] + m["fn"]
    m["answered"] = answered
    m["accuracy"] = (m["tp"] + m["tn"]) / answered if answered else None
    return m


def conflicts_of(judge: GeminiPairJudge, a, b) -> list:
    """Все конфликты пары: единица, вид, числовые токены, слова групп, скобки (вид, текст)."""
    out = []
    if a.get("unit") != b.get("unit"):
        out.append(("unit", f"{a.get('unit')} и {b.get('unit')}"))
    if a.get("kind") in ("work", "material") and b.get("kind") in ("work", "material") and a["kind"] != b["kind"]:
        out.append(("kind", f"{a['kind']} и {b['kind']}"))
    out.extend(judge.norm.conflicts(judge.norm.prepare(a["name"]), judge.norm.prepare(b["name"])))
    return out


def check_report(records, judge) -> dict:
    """Работа проверки кода: сколько ответов отклонено, по каким правилам, ловушки (пары с конфликтами) и ответ модели на них."""
    rep = {"rejected": 0, "by_kind": {}, "trap_pairs": [], "model_said_same_on_trap": 0}
    for r in records:
        conflicts = conflicts_of(judge, r["a"], r["b"])
        if outcome(r) == "rejected_by_check":
            rep["rejected"] += 1
            for kind in {k for k, _ in conflicts if k in {"unit", "kind"} | judge.hard}:
                rep["by_kind"][kind] = rep["by_kind"].get(kind, 0) + 1
        if conflicts:
            said = None if r["raw"] is None else r["raw"]["same_work"]
            rep["trap_pairs"].append({"a": r["a"].get("name_raw"), "b": r["b"].get("name_raw"),
                                      "conflicts": [f"{k}: {t}" for k, t in conflicts], "model_same": said,
                                      "outcome": outcome(r)})
            rep["model_said_same_on_trap"] += 1 if said else 0
    return rep


def first_row(conn, group_id):
    return conn.execute("SELECT i.source_file AS file, i.source_row AS row, g.name, g.status, g.final_work_key AS key "
                        "FROM staging_match_groups g JOIN staging_match_rows r ON r.group_id = g.group_id "
                        "JOIN items i ON i.item_id = r.item_id WHERE g.group_id = ? ORDER BY i.source_row LIMIT 1",
                        (group_id,)).fetchone()


def group_truth_set(conn, group_id, truth) -> set:
    return {truth[(r["source_file"], r["source_row"])] for r in conn.execute(
        "SELECT i.source_file, i.source_row FROM staging_match_rows r JOIN items i USING(item_id) WHERE r.group_id = ?", (group_id,))}


def diagnose(conn, group_id, truth, outcomes, project_id="demo") -> dict:
    """Что стало со строкой документа: статус, был ли правильный кандидат, что с ним сделал судья или проверка."""
    g = conn.execute("SELECT * FROM staging_match_groups WHERE group_id = ?", (group_id,)).fetchone()
    t = group_truth_set(conn, group_id, truth)
    vor_truth = {v["group_id"]: group_truth_set(conn, v["group_id"], truth) for v in conn.execute(
        "SELECT group_id FROM staging_match_groups WHERE project_id = ? AND doc_type = 'vor'", (project_id,))}
    vor_has = any(vt == t for vt in vor_truth.values())
    d = {"status": g["status"], "truth": sorted(t), "vor_has_pair": vor_has, "right_candidate": False, "verdict": ""}
    if g["status"] == "matched":
        ok = vor_truth.get(g["matched_group_id"]) == t
        d["verdict"] = "сопоставлена верно" if ok else "неверный ключ (склейка с другой работой)"
        return d
    me = first_row(conn, group_id)
    cands = conn.execute("SELECT * FROM staging_match_candidates WHERE group_id = ?", (group_id,)).fetchall()
    right = [c for c in cands if vor_truth.get(c["candidate_group_id"]) == t]
    d["right_candidate"] = bool(right)
    if not right:
        d["verdict"] = "нет в кандидатах" + ("" if cands else " (кандидатов нет вообще)")
        return d
    c = right[0]
    other = first_row(conn, c["candidate_group_id"])
    kind = outcomes.get((me["file"], me["row"], other["file"], other["row"]))
    if c["status"] == "rejected":
        why = (c["judge_reason"] or "")
        d["verdict"] = ("отклонено проверкой кода: " if why.startswith(CHECK_PREFIX) else "судья отклонил: ") + why[:120]
    elif c["status"] == "invalid":
        d["verdict"] = {"no_answer": "нет ответа (пары нет в кэше)",
                        "low_confidence": "ответ модели ниже min_confidence (нет решения)"}.get(kind, "нет ответа судьи")
    elif c["status"] == "superseded":
        d["verdict"] = "кандидат вытеснен другим выбором"
    else:
        d["verdict"] = f"кандидат в состоянии {c['status']}"
    return d


def evaluate_db(db, summary, gt_rows, trap_rows, truth) -> dict:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    issues = [dict(r) for r in conn.execute("SELECT * FROM issues_view")]
    res = ev.evaluate_issues(issues, gt_rows, trap_rows)
    states = vm.compare_db(conn, ev.PROJECT, truth)
    res.update(summary=summary, matched_ok=states["matched_ok"], false_merges=states["matched_wrong"],
               ambiguous=states["ambiguous"], false_absent=states["absent_wrong"], true_absent=states["absent_ok"])
    conn.close()
    return res


def row_group_id(conn, project_id, file, sheet, row):
    r = conn.execute("SELECT m.group_id FROM staging_match_rows m JOIN items i ON i.item_id = m.item_id WHERE i.project_id = ? "
                     "AND i.source_file = ? AND i.source_sheet = ? AND i.source_row = ?", (project_id, file, sheet, row)).fetchone()
    return r[0] if r else None


def not_found_reasons(db, gt_rows_not_found, truth, outcomes) -> list:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = []
    for gt in gt_rows_not_found:
        if gt["issue_type"] == "late_act":
            out.append((gt["gt_id"], gt["issue_type"], gt["canonical_name"], "акт не найден по дате или нет срока договора"))
            continue
        verdicts = []
        for file, sheet, row in sorted(ev.parse_related(gt["related_rows"])):
            if file.startswith("vor"):
                continue
            gid = row_group_id(conn, ev.PROJECT, file, sheet, row)
            if gid is None:
                continue
            d = diagnose(conn, gid, truth, outcomes)
            verdicts.append(f"{file}:{row} [{d['status']}] {d['verdict']}")
        if gt["issue_type"] == "missing_in_vor":
            why = "строка не absent: " + "; ".join(verdicts)
        elif all("сопоставлена верно" in v for v in verdicts):
            why = "строки сопоставлены верно, проверка не сработала (допуск, цена или валюта): " + "; ".join(verdicts)
        else:
            why = "; ".join(v for v in verdicts if "сопоставлена верно" not in v)
        out.append((gt["gt_id"], gt["issue_type"], gt["canonical_name"], why))
    conn.close()
    return out


def false_missing(db, issues_false, truth, outcomes) -> list:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = []
    for i in issues_false:
        if i["issue_type"] != "missing_in_vor":
            continue
        gid = row_group_id(conn, ev.PROJECT, i["source_file"], i["source_sheet"], i["source_row"])
        d = diagnose(conn, gid, truth, outcomes)
        out.append({"where": f"{i['source_file']}:{i['source_row']}", "name": first_row(conn, gid)["name"], **d})
    conn.close()
    return out


def md(headers, rows) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def metrics_row(label, r):
    precision = "-" if r["precision"] is None else f"{r['precision']:.2f}"
    return [label, f"{r['found']} из {r['gt_total']}", f"{r['false_count']} ({r['false_low_confidence']})", precision,
            f"{r['missing_found']} из {r['missing_total']}", f"{r['traps_triggered']} из {len(r['traps'])}",
            f"{r['ambiguous']} / {r['false_absent']}", r["false_merges"]]


def analyze(source, cfg, threshold=None) -> dict:
    """Весь анализ без печати (для тестов): -> словарь с матрицей, проверкой, метриками, причинами."""
    llm = {**cfg["rules"]["llm"], "cache_only": True}            # API не вызывается даже при ключе в окружении
    cfg = {**cfg, "rules": {**cfg["rules"], "llm": llm}}
    client = LlmClient(llm)
    judge = RecordingJudge(GeminiPairJudge(client, cfg))
    truth = vm.load_truth()
    gt_rows, trap_rows = ev.read_csv(ROOT / "data" / "ground_truth.csv"), ev.read_csv(ROOT / "data" / "traps.csv")
    th = threshold or cfg["rules"]["matching"]["fuzzy_threshold"]
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "real.db"
        summary = run_pipeline(source, db, "llm", judge=judge, project_id=ev.PROJECT, cfg=cfg, threshold=th, auto_ai=False)
        real = evaluate_db(db, summary, gt_rows, trap_rows, truth)
        outcomes = {(r["a"]["file"], r["a"]["row"], r["b"]["file"], r["b"]["row"]): outcome(r) for r in judge.records}
        reasons = not_found_reasons(db, real["not_found"], truth, outcomes)
        misses = false_missing(db, real["false_issues"], truth, outcomes)
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        extra = [dict(diagnose(conn, r["group_id"], truth, outcomes)) for r in conn.execute(
            "SELECT group_id FROM staging_match_groups WHERE project_id = ? AND doc_type != 'vor' AND status = 'ambiguous'", (ev.PROJECT,))]
        conn.close()
        base = ev.run_config(source, gt_rows, trap_rows, cfg, truth, "synonyms", th, False, tmp)
        ceiling = ev.run_config(source, gt_rows, trap_rows, cfg, truth, "synonyms_llm", th, True, tmp)
    return {"records": judge.records, "confusion": confusion(judge.records, truth), "checks": check_report(judge.records, judge.inner),
            "outcomes": {k: sum(1 for r in judge.records if outcome(r) == k) for k in
                         ("answered", "rejected_by_check", "low_confidence", "no_answer")},
            "stats": client.stats.as_dict(), "real": real, "base": base, "ceiling": ceiling, "reasons": reasons,
            "false_missing": misses, "ambiguous_rows": extra, "threshold": th, "cache_entries": sum(
                1 for _ in client.cache.dir.glob("[!_]*.json")) if client.cache.dir.is_dir() else 0}


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Оценка ответов Gemini по эталону (только кэш, без API)")
    parser.add_argument("--source", default=str(ROOT / "data" / "synthetic"))
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args(argv)
    a = analyze(args.source, cfg, args.threshold)
    c, o = a["confusion"], a["outcomes"]
    n = len(a["records"])
    print(f"Кэш: {a['cache_entries']} записей. Пар ушло судье: {n}; с ответом модели {c['answered']}, "
          f"без ответа (нет в кэше) {c['unanswered']}. Порог fuzzy {a['threshold']}. Вызовов API: {a['stats']['calls']}.\n")
    if c["unanswered"]:
        print(f"[!] Кэш неполный: {c['unanswered']} пар без ответа, цифры ниже по неполным данным.\n")

    print("## 1. Матрица ошибок по ответам модели (до проверок кода)\n")
    print(md(["Эталон \\ модель", "«одна работа»", "«разные»"],
             [["одна работа", f"верно: {c['tp']}", f"пропущено: {c['fn']}"],
              ["разные", f"ЛОЖНОЕ: {c['fp']}", f"верно: {c['tn']}"]]))
    acc = "-" if c["accuracy"] is None else f"{c['accuracy']:.2f} ({c['tp'] + c['tn']} из {c['answered']})"
    print(f"\nAccuracy: {acc}\n")
    print("Расхождения с эталоном:" if c["diffs"] else "Расхождений с эталоном нет.")
    if c["diffs"]:
        print(md(["Тип", "Название A (акт/смета)", "Название B (ВОР)", "Модель", "confidence", "Эталон", "reason"],
                 [[d["kind"], d["a"], d["b"], "одна" if d["model"] else "разные", d["confidence"],
                   "одна" if d["truth"] else "разные", d["reason"]] for d in c["diffs"]]))

    ch = a["checks"]
    print("\n## 2. Проверка кода и ловушки\n")
    print(md(["Исход пары", "Число"], [["принят ответ модели", o["answered"]], ["отклонено проверкой кода (rejected_by_check)", o["rejected_by_check"]],
                                       ["ответ ниже min_confidence (нет решения)", o["low_confidence"]], ["нет ответа (нет в кэше)", o["no_answer"]]]))
    print(f"\nОтклонено проверкой по правилам: {ch['by_kind'] or 'ни одной'}. "
          f"Пар с конфликтом (ловушки: единица, вид, d12/d8, М300/В25, внутренн./наружн., скобки): {len(ch['trap_pairs'])}, "
          f"из них модель сказала «одна работа»: {ch['model_said_same_on_trap']}.")
    for t in ch["trap_pairs"]:
        print(f"  - «{t['a']}» / «{t['b']}»: {'; '.join(t['conflicts'])}; модель: {t['model_same']}; исход: {t['outcome']}")

    print("\n## 3. evaluate.py: без ИИ, настоящий судья по кэшу, потолок\n")
    print(md(["Режим", "Найдено", "Ложные срабатывания (низкой уверенности)", "Precision", "Полнота missing_in_vor",
              "Ловушки сработали", "ambiguous / absent ложно", "Ложные склейки"],
             [metrics_row("без ИИ, со словарём", a["base"]), metrics_row("настоящий судья Gemini (по кэшу)", a["real"]),
              metrics_row("потолок: фейковые судьи по эталону (НЕ оценка модели)", a["ceiling"])]))
    print(f"\nНайдено настоящим судьёй: {', '.join(a['real']['found_ids']) or '-'}; без ИИ: {', '.join(a['base']['found_ids']) or '-'}")

    print("\n## 4. Ненайденные GT (настоящий судья) и причины\n")
    print(md(["GT", "Тип", "Работа", "Причина"], [list(r) for r in a["reasons"]]) if a["reasons"] else "Все GT найдены.")

    print("\n## 5. Ложные missing_in_vor\n")
    fm = a["false_missing"]
    if fm:
        print(md(["Строка", "Название", "Пара в ВОР есть", "Правильная пара была в кандидатах", "Что с ней стало"],
                 [[m["where"], m["name"], "да" if m["vor_has_pair"] else "нет", "да" if m["right_candidate"] else "нет", m["verdict"]] for m in fm]))
        closed = sum(1 for m in fm if m["vor_has_pair"])
        print(f"\nВсего ложных: {len(fm)}; правильная пара была в кандидатах у {sum(1 for m in fm if m['right_candidate'])}; "
              f"RowMatcher видит весь список ВОР и может закрыть те, у кого пара в ВОР есть: {closed} из {len(fm)}.")
    else:
        print("Ложных missing_in_vor нет.")
    amb = a["ambiguous_rows"]
    print(f"\nСтроки ambiguous (в issues не идут, но без решения): {len(amb)}; пара в ВОР есть у {sum(1 for r in amb if r['vor_has_pair'])}, "
          f"правильный кандидат был у {sum(1 for r in amb if r['right_candidate'])}. Это тоже поле для RowMatcher.")
    print("\nОговорки: данные синтетические, словарь составлен по тем же названиям, цифры оптимистичны. Строка «потолок» "
          "это фейковые судьи по эталону, а не оценка модели. Оценка по неполному кэшу не использовать как итог.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
