#!/usr/bin/env python
"""Проверка точности matching: python scripts/verify_matching.py [--db data/cache/demo.db] [-v]

Сравнивает сопоставление с эталоном генератора: журнал Generator.log знает item_no каждой строки (какая строка к какой
работе относится). Считаем по строкам документов (смета и акты):
  правильно    группа строк сопоставлена со строкой ВОР той же работы;
  ложная склейка  сопоставлена с ВОР другой работы (это хуже всего);
  не сопоставлена, и так должно быть  позиции без ВОР (отмостка, видеонаблюдение: GT-9, GT-10);
  ложная «не сопоставлена»  пара в ВОР есть, но не найдена; из них: нужная пара есть среди кандидатов для LLM,
  в кандидатах только чужие, кандидатов нет.
Состояния строки (спецификация §6): matched / ambiguous / absent. Колонки: matched верно, ложная склейка, ambiguous,
absent верно (позиции без ВОР), absent ложно (пара в ВОР есть, но кандидатов нет: порождает ложный missing_in_vor).
Строки «потолок» показывают, что получится, если судья (PairJudge) и ИИ-матчер (RowMatcher) отвечают по эталону генератора:
это верхняя граница при идеальном ИИ, а не оценка качества настоящей модели.
Генерация идёт во временную папку, файлы в data/ не трогаются. Пороги под результат не подгоняются.
Оговорка: словарь synonyms.yaml составлен по синтетике, цифры оптимистичны.
"""
import argparse
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.matching import (compute_matching, load_rows, resolve_candidates, resolve_rows, save_matching)  # noqa: E402

NO_VOR_ITEMS = {"X1", "X2"}      # позиции, которых нет в ВОР: «не сопоставлена» для них правильный результат


def load_truth() -> dict:
    """(файл, строка) -> item_no по журналу генератора."""
    spec = importlib.util.spec_from_file_location("generate_synthetic", ROOT / "scripts" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with tempfile.TemporaryDirectory() as tmp:
        generated = mod.generate(out_dir=tmp, meta_dir=tmp)
    return {(r["file"], r["row"]): r["item_no"] for r in generated.log}


def group_truth(group, truth) -> set:
    return {truth[(r.file, r.source_row)] for r in group.rows}


def compare(result, truth) -> dict:
    """Метрики по строкам документов + списки для разбора."""
    vor_truth = {g.gid: group_truth(g, truth) for g in result.groups if g.is_vor}
    out = {"correct": 0, "wrong": 0, "true_missing": 0, "false_unmatched": 0, "cand_right": 0, "cand_wrong": 0,
           "cand_none": 0, "wrong_pairs": [], "false_unmatched_list": [], "vor_mixed": [],
           "candidate_groups": len({c.doc.gid for c in result.candidates})}
    out["vor_mixed"] = [g.name for g in result.groups if g.is_vor and len(vor_truth[g.gid]) > 1]
    for p in result.pairs:
        n = len(p.doc.rows)
        if group_truth(p.doc, truth) == vor_truth[p.vor.gid]:
            out["correct"] += n
        else:
            out["wrong"] += n
            out["wrong_pairs"].append((p.doc.first.file, p.doc.first.source_row, p.doc.name, p.vor.name, p.score))
    by_group = {}
    for c in result.candidates:
        by_group.setdefault(c.doc.gid, []).append(c)
    for g in result.unmatched:
        n, t = len(g.rows), group_truth(g, truth)
        if t <= NO_VOR_ITEMS:
            out["true_missing"] += n
            continue
        out["false_unmatched"] += n
        cands = by_group.get(g.gid, [])
        if any(vor_truth[c.vor.gid] == t for c in cands):
            kind = "cand_right"
        elif cands:
            kind = "cand_wrong"
        else:
            kind = "cand_none"
        out[kind] += n
        out["false_unmatched_list"].append((g.first.file, g.first.source_row, g.name, kind))
    out["rows"] = out["correct"] + out["wrong"] + out["true_missing"] + out["false_unmatched"]
    return out


def compare_db(conn, project_id, truth) -> dict:
    """Метрики по состоянию в БД (после save_matching и, возможно, resolve_candidates / resolve_rows), по строкам документов."""
    def rows_of(group_id):
        return conn.execute("SELECT i.source_file, i.source_row FROM staging_match_rows r JOIN items i USING(item_id) "
                            "WHERE r.group_id = ?", (group_id,)).fetchall()

    def truth_set(group_id):
        return {truth[(r["source_file"], r["source_row"])] for r in rows_of(group_id)}

    out = {"matched_ok": 0, "matched_wrong": 0, "ambiguous": 0, "ambiguous_right_cand": 0, "absent_ok": 0, "absent_wrong": 0,
           "llm_rows": 0, "wrong_pairs": [], "absent_wrong_list": [], "ambiguous_list": []}
    vor_truth = {g["group_id"]: truth_set(g["group_id"]) for g in conn.execute(
        "SELECT group_id FROM staging_match_groups WHERE project_id = ? AND doc_type = 'vor'", (project_id,))}
    for g in conn.execute("SELECT * FROM staging_match_groups WHERE project_id = ? AND doc_type != 'vor' ORDER BY doc_id, first_item_id",
                          (project_id,)).fetchall():
        n, t = len(rows_of(g["group_id"])), truth_set(g["group_id"])
        first = rows_of(g["group_id"])[0]
        label = (first["source_file"], first["source_row"], g["name"])
        if g["status"] == "matched":
            if t == vor_truth[g["matched_group_id"]]:
                out["matched_ok"] += n
            else:
                out["matched_wrong"] += n
                out["wrong_pairs"].append(label + (conn.execute("SELECT name FROM staging_match_groups WHERE group_id = ?",
                                                                (g["matched_group_id"],)).fetchone()[0],))
            if conn.execute("SELECT 1 FROM staging_matches_ext WHERE group_id = ? AND stage IN ('llm', 'llm_row')", (g["group_id"],)).fetchone():
                out["llm_rows"] += n
        elif g["status"] == "ambiguous":
            out["ambiguous"] += n
            cands = conn.execute("SELECT candidate_group_id FROM staging_match_candidates WHERE group_id = ?", (g["group_id"],)).fetchall()
            right = any(vor_truth[c["candidate_group_id"]] == t for c in cands)
            out["ambiguous_right_cand"] += n if right else 0
            out["ambiguous_list"].append(label + (right,))
        else:                                                    # absent
            if t <= NO_VOR_ITEMS:
                out["absent_ok"] += n
            else:
                out["absent_wrong"] += n
                out["absent_wrong_list"].append(label)
    out["rows"] = out["matched_ok"] + out["matched_wrong"] + out["ambiguous"] + out["absent_ok"] + out["absent_wrong"]
    return out


class TruthJudge:
    """Фейковый PairJudge по эталону генератора: потолок при идеальном судье."""
    available = True

    def __init__(self, truth):
        self.truth = truth

    def judge_pair(self, a, b, context):
        same = self.truth.get((a["file"], a["row"])) == self.truth.get((b["file"], b["row"]))
        return {"same_work": same, "confidence": 1.0, "reason": "эталон генератора"}


class TruthRowMatcher:
    """Фейковый RowMatcher по эталону генератора: выбирает ключ ВОР той же работы или None."""
    available = True

    def __init__(self, truth):
        self.truth = truth

    def match_row(self, row, vor_keys):
        t = self.truth.get((row["file"], row["row"]))
        for k in vor_keys:
            if self.truth.get((k["file"], k["row"])) == t:
                return {"key": k["key"], "confidence": 1.0, "reason": "эталон генератора"}
        return {"key": None, "confidence": 1.0, "reason": "в ВОР нет такой работы (эталон генератора)"}


def run_config(base_conn, project_id, cfg, truth, use_synonyms, threshold, missing_side=None, judge=None, row_matcher=None):
    """Один прогон matching в копии БД в памяти: исходная БД не меняется. -> метрики compare_db."""
    import sqlite3
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    base_conn.backup(mem)
    result = compute_matching(load_rows(mem, project_id), cfg, use_synonyms, threshold, missing_side)
    save_matching(mem, result, project_id, cfg)
    if judge is not None:
        resolve_candidates(mem, judge, cfg, project_id)
    if row_matcher is not None:
        resolve_rows(mem, row_matcher, cfg, project_id)
    metrics = compare_db(mem, project_id, truth)
    mem.close()
    return metrics


CONFIGS = [  # (подпись, use_synonyms, missing_side)
    ("без синонимов", False, None),
    ("с синонимами, missing_side=block", True, "block"),
    ("с синонимами, missing_side=allow", True, "allow"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Точность matching по эталону генератора")
    parser.add_argument("--db", default=str(ROOT / "data" / "cache" / "demo.db"))
    parser.add_argument("--project", default="demo")
    parser.add_argument("-v", "--verbose", action="store_true", help="печатать ложные склейки и ложные «не сопоставлена»")
    args = parser.parse_args()
    cfg = load_config()
    conn = get_connection(args.db)
    rows = load_rows(conn, args.project)
    truth = load_truth()
    header = (f"  {'режим':<44}{'порог':>6}{'matched верно':>15}{'ложная склейка':>16}{'ambiguous':>11}"
              f"{'(нужная пара в канд.)':>23}{'absent верно':>14}{'absent ложно':>14}")
    print(f"Строки документов (смета и акты), всего {len(rows) - len([r for r in rows if r.doc_type == 'vor'])}:")
    print(header)
    def line(label, th, m):
        print(f"  {label:<44}{th:>6}{m['matched_ok']:>15}{m['matched_wrong']:>16}{m['ambiguous']:>11}"
              f"{m['ambiguous_right_cand']:>23}{m['absent_ok']:>14}{m['absent_wrong']:>14}")
        if args.verbose:
            for f, r, a, b in m["wrong_pairs"]:
                print(f"      ЛОЖНАЯ СКЛЕЙКА {f}:{r} «{a}» -> «{b}»")
            for f, r, a in m["absent_wrong_list"]:
                print(f"      absent ложно {f}:{r} «{a}»")
            for f, r, a, right in m["ambiguous_list"]:
                print(f"      ambiguous {f}:{r} «{a}» [{'нужная пара среди кандидатов' if right else 'нужной пары в кандидатах нет'}]")
    for label, syn, side in CONFIGS:
        for th in cfg["rules"]["evaluate"]["thresholds"]:
            line(label, th, run_config(conn, args.project, cfg, truth, syn, th, side))
    print("  потолок при идеальном ИИ (фейковые судьи по эталону генератора):")
    for th in cfg["rules"]["evaluate"]["thresholds"]:
        line("PairJudge по эталону", th, run_config(conn, args.project, cfg, truth, True, th, judge=TruthJudge(truth)))
        line("PairJudge + RowMatcher по эталону", th, run_config(conn, args.project, cfg, truth, True, th, judge=TruthJudge(truth),
                                                                   row_matcher=TruthRowMatcher(truth)))
    print("\nОговорка: словарь synonyms.yaml составлен по синтетике, цифры оптимистичны; на реальных документах они ниже.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
