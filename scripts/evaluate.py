#!/usr/bin/env python
"""Оценка качества по docs/synthetic_spec.md §8: python scripts/evaluate.py [--ai-ceiling]

Для каждого режима (no_synonyms, synonyms, synonyms_llm) и порога (85, 90) прогоняет run_pipeline на data/synthetic и сверяет issues
с data/ground_truth.csv и data/traps.csv.
  GT найден, если есть issue того же типа, у которого (файл, лист, строка) входит в related_rows этого GT
  (late_act: по типу и файлу акта); несколько issues на один GT это одно попадание.
  Ложное срабатывание: issue, который не соответствует ни одному GT. Precision = issues, соответствующие GT / все issues.
  Ловушка (traps.csv) сработала, если есть issue любого типа в её related_rows.
  Ложные «не сопоставлено»: строки сметы и актов без пары (ambiguous и absent), для которых в GT нет missing_in_vor;
  ложные absent отдельно (они порождают ложные missing_in_vor в режиме без ИИ).
Режим synonyms_llm без реального ИИ пропускается; с флагом --ai-ceiling идёт с фейковыми судьями по эталону генератора и помечается
«потолок, не оценка модели».
Оговорка: данные синтетические, словарь synonyms.yaml составлен по тем же названиям, поэтому цифры оптимистичны.
"""
import argparse
import csv
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import verify_matching as vm  # noqa: E402
from src.config import load_config  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

PROJECT = "demo"
MODE_LABELS = {
    "no_synonyms": "без ИИ, без словаря",
    "synonyms": "без ИИ, со словарём",
    "synonyms_llm": "с ИИ (потолок, не оценка модели)",
}


def parse_related(text: str) -> set:
    """«файл:лист:строка;…» -> {(файл, лист, строка)}."""
    out = set()
    for ref in text.split(";"):
        file, sheet, row = ref.split(":")
        out.add((file, sheet, int(row)))
    return out


def read_csv(path) -> list:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def issue_hits_gt(issue: dict, gt: dict) -> bool:
    if issue["issue_type"] != gt["issue_type"]:
        return False
    if gt["issue_type"] == "late_act":
        return issue["source_file"] == gt["source_file"]
    return (issue["source_file"], issue["source_sheet"], issue["source_row"]) in parse_related(gt["related_rows"])


def evaluate_issues(issues: list, gt_rows: list, trap_rows: list) -> dict:
    """issues: словари с issue_type, source_file, source_sheet, source_row. -> метрики и списки для разбора."""
    found = [g for g in gt_rows if any(issue_hits_gt(i, g) for i in issues)]
    not_found = [g for g in gt_rows if g not in found]
    true_issues = [i for i in issues if any(issue_hits_gt(i, g) for g in gt_rows)]
    false_issues = [i for i in issues if i not in true_issues]
    missing_gt = [g for g in gt_rows if g["issue_type"] == "missing_in_vor"]
    traps = []
    for t in trap_rows:
        related = parse_related(t["related_rows"])
        hit = [i for i in issues if (i["source_file"], i["source_sheet"], i["source_row"]) in related]
        traps.append({"trap_id": t["trap_id"], "triggered": bool(hit), "issues": hit})
    return {
        "gt_total": len(gt_rows), "found": len(found), "found_ids": [g["gt_id"] for g in found],
        "not_found": not_found, "issues": len(issues), "true_issues": len(true_issues),
        "false_issues": false_issues, "false_count": len(false_issues),
        "false_low_confidence": sum(1 for i in false_issues if i.get("confidence") == "low"),
        "precision": len(true_issues) / len(issues) if issues else None,
        "recall": len(found) / len(gt_rows) if gt_rows else None,
        "missing_total": len(missing_gt), "missing_found": sum(1 for g in missing_gt if g in found),
        "traps": traps, "traps_triggered": sum(1 for t in traps if t["triggered"]),
    }


def explain_not_found(conn, gt: dict, project_id: str = PROJECT) -> str:
    """Почему GT не найден: состояния связанных строк сметы и актов после matching."""
    if gt["issue_type"] == "late_act":
        return "акт не найден по дате или нет срока договора"
    states, wrong = [], []
    for file, sheet, row in sorted(parse_related(gt["related_rows"])):
        if file.startswith("vor"):
            continue
        r = conn.execute(
            "SELECT g.status, g.final_work_key FROM staging_match_rows m JOIN items i ON i.item_id = m.item_id "
            "JOIN staging_match_groups g ON g.group_id = m.group_id WHERE i.project_id = ? AND i.source_file = ? AND i.source_sheet = ? "
            "AND i.source_row = ?", (project_id, file, sheet, row)).fetchone()
        if r:
            states.append(f"{file}:{row} {r['status']}")
            if gt["issue_type"] == "missing_in_vor" and r["status"] != "absent":
                wrong.append(f"{file}:{row}")
    unresolved = [s for s in states if s.endswith(("ambiguous", "absent"))]
    if gt["issue_type"] == "missing_in_vor":
        why = "строка не absent: " + ", ".join(wrong) if wrong else "issue не создан"
    elif unresolved:
        why = ("строки без пары (сопоставление не решено без ИИ), проверка не может сравнить объём или цену: "
               + ", ".join(unresolved))
    else:
        why = "строки сопоставлены, но проверка не сработала (допуск, цена сметы или валюта)"
    return f"{why}; состояния: {', '.join(states) or '-'}"


def run_config(source, gt_rows, trap_rows, cfg, truth, mode_name, threshold, ai_ceiling, tmp_dir):
    """Один прогон конфигурации. -> словарь метрик или None, если режим пропущен."""
    if mode_name == "synonyms_llm" and not ai_ceiling:
        return None
    db = Path(tmp_dir) / f"{mode_name}_{threshold}.db"
    kwargs = {"use_synonyms": mode_name != "no_synonyms", "threshold": threshold, "project_id": PROJECT, "cfg": cfg}
    if mode_name == "synonyms_llm":
        summary = run_pipeline(source, db, "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth), **kwargs)
    else:
        summary = run_pipeline(source, db, "rules_only", **kwargs)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    issues = [dict(r) for r in conn.execute("SELECT * FROM issues_view")]
    result = evaluate_issues(issues, gt_rows, trap_rows)
    states = vm.compare_db(conn, PROJECT, truth)
    # ложные «не сопоставлено»: ambiguous и absent строки, у которых пары в GT-missing_in_vor нет (то есть пара в ВОР была)
    result.update(summary=summary, matched_ok=states["matched_ok"], false_merges=states["matched_wrong"],
                  ambiguous=states["ambiguous"], false_absent=states["absent_wrong"], true_absent=states["absent_ok"],
                  false_unmatched=states["ambiguous"] + states["absent_wrong"], not_found_why=[
                      (g["gt_id"], g["issue_type"], g["canonical_name"], explain_not_found(conn, g)) for g in result["not_found"]])
    conn.close()
    return result


def slide_table(results: dict, thresholds) -> str:
    lines = ["| Режим | Порог | Найдено из N | Ложные срабатывания (из них низкой уверенности) | Полнота missing_in_vor | Ловушки сработали | "
             "Ложные «не сопоставлено» (ambiguous / absent) | Ложные склейки |", "|---|---|---|---|---|---|---|---|"]
    for mode in ("no_synonyms", "synonyms", "synonyms_llm"):
        for th in thresholds:
            r = results.get((mode, th))
            if r is None:
                lines.append(f"| {MODE_LABELS[mode]} | {th} | пропущен: реальный ИИ не подключён | | | | | |")
                continue
            lines.append(f"| {MODE_LABELS[mode]} | {th} | {r['found']} из {r['gt_total']} | {r['false_count']} ({r['false_low_confidence']}) | "
                         f"{r['missing_found']} из {r['missing_total']} | {r['traps_triggered']} из {len(r['traps'])} | "
                         f"{r['false_unmatched']} ({r['ambiguous']} / {r['false_absent']}) | {r['false_merges']} |")
    return "\n".join(lines)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Оценка: найдено X из N, ложные срабатывания, ловушки, режимы без ИИ и с ИИ")
    parser.add_argument("--source", default=str(ROOT / "data" / "synthetic"))
    parser.add_argument("--gt", default=str(ROOT / "data" / "ground_truth.csv"))
    parser.add_argument("--traps", default=str(ROOT / "data" / "traps.csv"))
    parser.add_argument("--ai-ceiling", action="store_true",
                        help="режим synonyms_llm с фейковыми судьями по эталону генератора (потолок, не оценка модели)")
    parser.add_argument("-v", "--verbose", action="store_true", help="ложные срабатывания и ложные «не сопоставлено» списком")
    args = parser.parse_args()

    gt_rows, trap_rows = read_csv(args.gt), read_csv(args.traps)
    truth = vm.load_truth()
    thresholds = cfg["rules"]["evaluate"]["thresholds"]
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        for mode in cfg["rules"]["evaluate"]["modes"]:
            for th in thresholds:
                results[(mode, th)] = run_config(args.source, gt_rows, trap_rows, cfg, truth, mode, th, args.ai_ceiling, tmp)
    print("Оценка на синтетике (данные искусственные, словарь составлен по тем же названиям: цифры оптимистичны).\n")
    for (mode, th), r in results.items():
        if r is None:
            print(f"[{MODE_LABELS[mode]}] порог {th}: ПРОПУЩЕН, реальный ИИ не подключён (запуск с --ai-ceiling даст потолок по эталону, "
                  f"это не оценка модели)")
            continue
        print(f"[{MODE_LABELS[mode]}] порог {th}: найдено {r['found']} из {r['gt_total']} (GT {', '.join(r['found_ids']) or '-'}), "
              f"issues {r['issues']}, ложных срабатываний {r['false_count']} (низкой уверенности {r['false_low_confidence']}), precision "
              f"{'-' if r['precision'] is None else format(r['precision'], '.2f')}, полнота missing_in_vor {r['missing_found']} из "
              f"{r['missing_total']}, ловушки сработали {r['traps_triggered']} из {len(r['traps'])}"
              f"{[t['trap_id'] for t in r['traps'] if t['triggered']] or ''}")
        print(f"    сопоставление: верно {r['matched_ok']}, ложных склеек {r['false_merges']}, ambiguous {r['ambiguous']}, "
              f"absent верно {r['true_absent']}, absent ложно {r['false_absent']}")
        if args.verbose:
            for i in r["false_issues"]:
                print(f"    ложное срабатывание: {i['issue_type']} {i['source_file']}:{i['source_sheet']}:{i['source_row']} {i['work_key']}")
    print("\nКакие GT не найдены и почему:")
    for key in [(m, th) for m in ("synonyms", "synonyms_llm") for th in thresholds]:
        r = results.get(key)
        if r is None:
            continue
        print(f"  режим «{MODE_LABELS[key[0]]}», порог {key[1]}:" + ("" if r["not_found_why"] else " все GT найдены"))
        for gid, itype, name, why in r["not_found_why"]:
            print(f"    GT-{gid} {itype} «{name}»: {why}")
    print("\nИтоговая таблица для слайда («без ИИ / с ИИ»):\n")
    print(slide_table(results, thresholds))
    print("\nОговорки: данные синтетические; словарь synonyms.yaml и must_match_tokens составлены по тем же названиям, поэтому цифры "
          "оптимистичны и на реальных документах будут ниже. Строка «с ИИ» это потолок с фейковыми судьями по эталону генератора, "
          "а не оценка настоящей модели; без реального ИИ режим не подменяется другим, а пропускается.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
