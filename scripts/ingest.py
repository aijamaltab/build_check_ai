#!/usr/bin/env python
"""Загрузка папки с Excel в SQLite: python scripts/ingest.py data/synthetic --db data/cache/demo.db

По каждому файлу печатает: строк прочитано, не распознано, dq не пройдено. В конце: items по doc_type.
Matching, проверки расхождений, интерфейс и LLM здесь не запускаются.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.db import get_connection  # noqa: E402
from src.ingestion import ingest_dir  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Excel -> items в SQLite")
    parser.add_argument("folder", help="папка с .xlsx")
    parser.add_argument("--db", default=str(ROOT / "data" / "cache" / "demo.db"))
    parser.add_argument("--project", default="demo", help="project_id")
    args = parser.parse_args()

    conn = get_connection(args.db)
    reports = ingest_dir(conn, args.folder, args.project, load_config())
    print(f"{'файл':<16}{'тип':<10}{'шаблон':<12}{'прочитано':>10}{'не распознано':>15}{'dq не пройдено':>16}  статус")
    for r in reports:
        print(f"{r.file:<16}{r.doc_type or '-':<10}{r.template or '-':<12}{r.rows_read:>10}"
              f"{len(r.unrecognized):>15}{len(r.dq_failed):>16}  {r.status}" + (f"  ({r.error})" if r.error else ""))
        for row, why in r.unrecognized:
            print(f"    не распознано, строка {row}: {why}")
        for name, details in r.dq_failed:
            print(f"    dq «{name}»: {details}")
    print("\nitems по doc_type:")
    rows = conn.execute("SELECT doc_type, COUNT(*) n FROM items WHERE project_id = ? GROUP BY doc_type ORDER BY doc_type",
                        (args.project,))
    for row in rows:
        print(f"  {row['doc_type']:<10}{row['n']:>5}")
    total = conn.execute("SELECT COUNT(*) FROM items WHERE project_id = ?", (args.project,)).fetchone()[0]
    print(f"  {'всего':<10}{total:>5}\nБаза: {args.db}")
    conn.close()
    return 1 if any(r.status == "error" for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
