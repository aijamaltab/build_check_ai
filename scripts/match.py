#!/usr/bin/env python
"""Сопоставление позиций: python scripts/match.py --db data/cache/demo.db --mode rules_only

Читает items после scripts/ingest.py. Печатает для порогов 85 и 90 (config/rules.yaml, evaluate.thresholds):
сколько строк сопоставлено по методам (exact / fuzzy / llm), сколько групп ушло в кандидаты для LLM, сколько не сопоставлено.
Результат одного порога (--threshold, по умолчанию matching.fuzzy_threshold) записывается в БД и разбирается подробно.
Реального LLM-судьи здесь нет: режим llm использует NoopJudge, пока судью не подключит напарница.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.matching import NoopJudge, compute_matching, load_rows, resolve_candidates, save_matching  # noqa: E402


def stats_line(res) -> str:
    by_method = {"exact": 0, "fuzzy": 0, "llm": 0}
    by_stage = {"exact": 0, "synonyms": 0, "fuzzy": 0}
    for p in res.pairs:
        by_method[p.method] += len(p.doc.rows)
        by_stage[p.stage] += len(p.doc.rows)
    cand_groups = {c.doc.gid for c in res.candidates}
    cand_rows = sum(len(g.rows) for g in res.unmatched if g.gid in cand_groups)
    unmatched_rows = sum(len(g.rows) for g in res.unmatched)
    return (f"сопоставлено строк: exact {by_method['exact']} (из них по словарю {by_stage['synonyms']}), "
            f"fuzzy {by_method['fuzzy']}, llm {by_method['llm']}; в кандидатах для LLM {cand_rows} строк "
            f"({len(cand_groups)} групп); не сопоставлено {unmatched_rows} строк ({len(res.unmatched)} групп); "
            f"заблокировано числовыми токенами пар: {len(res.blocked)}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Matching позиций между документами")
    parser.add_argument("--db", default=str(ROOT / "data" / "cache" / "demo.db"))
    parser.add_argument("--project", default="demo")
    parser.add_argument("--mode", choices=cfg["rules"]["llm"]["modes"], default="rules_only")
    parser.add_argument("--no-synonyms", action="store_true", help="без словаря и защит (базовая линия rapidfuzz)")
    parser.add_argument("--threshold", type=float, default=cfg["rules"]["matching"]["fuzzy_threshold"],
                        help="порог, результат которого записывается в БД")
    args = parser.parse_args()

    conn = get_connection(args.db)
    rows = load_rows(conn, args.project)
    if not rows:
        print("В базе нет items: сначала python scripts/ingest.py data/synthetic --db", args.db)
        return 1
    use_syn = not args.no_synonyms
    print(f"Режим: {args.mode}; словарь: {'да' if use_syn else 'нет'}")
    if args.mode == "llm":
        print("LLM-судья не подключён (его реализует напарница): используется NoopJudge, кандидаты остаются открытыми.")
    for th in cfg["rules"]["evaluate"]["thresholds"]:
        print(f"  порог {th}: {stats_line(compute_matching(rows, cfg, use_syn, th))}")

    result = compute_matching(rows, cfg, use_syn, args.threshold)
    save_matching(conn, result, args.project, cfg, args.mode)
    judge_stats = resolve_candidates(conn, NoopJudge(), cfg, args.project)
    print(f"\nЗаписано в БД (порог {args.threshold:g}): {stats_line(result)}")
    print(f"Судья: {judge_stats.skipped} кандидатов не разбирались (судья недоступен)")
    print("\nНе сопоставлено (файл:лист:строка), для порога", f"{args.threshold:g}:")
    for g in result.unmatched:
        has = any(c.doc.gid == g.gid for c in result.candidates)
        refs = ", ".join(f"{r.file}:{r.sheet}:{r.source_row}" for r in g.rows)
        print(f"  {refs}  «{g.first.name_raw}»  {'[кандидат для LLM]' if has else '[кандидатов нет]'}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
