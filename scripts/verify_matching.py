#!/usr/bin/env python
"""Проверка точности matching: python scripts/verify_matching.py [--db data/cache/demo.db] [-v]

Сравнивает сопоставление с эталоном генератора: журнал Generator.log знает item_no каждой строки (какая строка к какой
работе относится). Считаем по строкам документов (смета и акты):
  правильно    группа строк сопоставлена со строкой ВОР той же работы;
  ложная склейка  сопоставлена с ВОР другой работы (это хуже всего);
  не сопоставлена, и так должно быть  позиции без ВОР (отмостка, видеонаблюдение: GT-9, GT-10);
  ложная «не сопоставлена»  пара в ВОР есть, но не найдена; из них: нужная пара есть среди кандидатов для LLM,
  в кандидатах только чужие, кандидатов нет.
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
from src.matching import compute_matching, load_rows  # noqa: E402

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
    print("Строки документов (смета и акты): правильно / ложные склейки / не сопоставлена, и так должно быть / "
          "ложные «не сопоставлена» (из них: нужная пара в кандидатах LLM / только чужие / кандидатов нет)")
    for label, syn, side in CONFIGS:
        for th in cfg["rules"]["evaluate"]["thresholds"]:
            res = compute_matching(rows, cfg, syn, th, side)
            m = compare(res, truth)
            print(f"  {label:<34} порог {th}: из {m['rows']}: правильно {m['correct']}, ложных склеек {m['wrong']}, "
                  f"верно не сопоставлено {m['true_missing']}, ложных «не сопоставлена» {m['false_unmatched']} "
                  f"({m['cand_right']} / {m['cand_wrong']} / {m['cand_none']}), ложных слияний внутри ВОР {len(m['vor_mixed'])}")
            if args.verbose:
                for f, r, a, b, s in m["wrong_pairs"]:
                    print(f"      ЛОЖНАЯ СКЛЕЙКА {f}:{r} «{a}» -> «{b}» (score {s:.0f})")
                for f, r, a, kind in m["false_unmatched_list"]:
                    print(f"      не сопоставлена {f}:{r} «{a}» [{kind}]")
    print("\nОговорка: словарь synonyms.yaml составлен по синтетике, цифры оптимистичны; на реальных документах они ниже.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
