#!/usr/bin/env python
"""Сквозной сценарий в консоли: ingest -> matching -> проверки -> сводка.

  python scripts/run_all.py                       # режим rules_only (без ИИ, с баннером)
  python scripts/run_all.py --mode llm --ai-ceiling   # режим llm с фейковыми судьями по эталону генератора (потолок, не модель)

Без реального ИИ режим llm не подменяется: прогон идёт как rules_only, и баннер это показывает.
Реальный PairJudge и RowMatcher на Gemini подключит отдельный модуль.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.config import load_config  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402

DISCLAIMER = ("Система сверяет документы между собой и не доказывает фактическое выполнение работ; "
              "окончательное решение за специалистом.")


def fake_judges():
    """Фейковые судьи по эталону генератора (потолок при идеальном ИИ). Только для демонстрации и тестов."""
    import verify_matching as vm
    truth = vm.load_truth()
    return vm.TruthJudge(truth), vm.TruthRowMatcher(truth)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    parser = argparse.ArgumentParser(description="Сквозной прогон: файлы -> расхождения -> сводка")
    parser.add_argument("--source", default=str(ROOT / "data" / "synthetic"), help="папка с .xlsx")
    parser.add_argument("--db", default=str(ROOT / "data" / "cache" / "demo.db"))
    parser.add_argument("--mode", choices=cfg["rules"]["llm"]["modes"], default="rules_only")
    parser.add_argument("--ai-ceiling", action="store_true", help="фейковые судьи по эталону (потолок, не оценка модели)")
    parser.add_argument("--no-synonyms", action="store_true")
    parser.add_argument("--threshold", type=float, default=None)
    args = parser.parse_args(argv)

    judge = row_matcher = None
    if args.mode == "llm" and args.ai_ceiling:
        judge, row_matcher = fake_judges()
    summary = run_pipeline(args.source, args.db, args.mode, judge, row_matcher, use_synonyms=not args.no_synonyms,
                           threshold=args.threshold, cfg=cfg)
    if summary["banner"]:
        print(f"[!] {summary['banner']}" + (" (запрошен режим llm)" if summary["requested_mode"] == "llm" else ""))
    elif args.ai_ceiling:
        print("[i] режим llm с фейковыми судьями по эталону: это потолок, а не оценка модели")
    print(summary["text"])
    print(f"Позиции по светофору: красных {summary['statuses']['red']}, жёлтых {summary['statuses']['yellow']}, "
          f"зелёных {summary['statuses']['green']}")
    if summary["caveat"]:
        print("[!] " + summary["caveat"])
    if summary["documents_with_errors"]:
        print("Файлы с проблемами качества данных (требуют проверки):", ", ".join(summary["documents_with_errors"]))

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    print("\nРасхождения (по влиянию на бюджет, сом):")
    for r in conn.execute("SELECT * FROM issues_view WHERE project_id = 'demo'"):
        impact = "—" if r["impact_som"] is None else f"{r['impact_som']:,.0f}".replace(",", " ")
        low = " [низкая уверенность]" if r["confidence"] == "low" else ""
        print(f"  {r['issue_type']:<17}{r['severity']:<8}{impact:>12}  {r['source_file']}:{r['source_sheet']}:{r['source_row']}{low}")
        print(f"      {r['explanation']}")
    unresolved = conn.execute("SELECT COUNT(*) FROM position_status WHERE review_rows > 0").fetchone()[0]
    if unresolved:
        print(f"\nПозиций с неразобранными строками (требуют проверки): {unresolved}")
    print("\n" + DISCLAIMER)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
