#!/usr/bin/env python
"""Проверка точности ingestion: python scripts/verify_ingestion.py --db data/cache/demo.db

Сверяет items в базе с журналом генератора (он знает, какие строки и значения записал) и с ground_truth.csv:
  1. по каждому файлу те же строки (лист, номер), то же количество после нормализации, цена и сумма;
  2. каждая строка из related_rows ground_truth.csv есть в items (для late_act это строка заголовка акта,
     её номер хранится в staging_documents_ext.date_source_row);
  3. суммы по ключам ВОР-2 (кабель, светильники, радиаторы, трубы, мусор) после умножения на множитель;
  4. итог акта №2 в items не попал и равен сумме строк.
Генерация идёт во временную папку, файлы в data/ не трогаются. Ничего не подгоняется: расхождения печатаются.
"""
import argparse
import csv
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db import get_connection  # noqa: E402

TOL = 1e-6


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_synthetic", ROOT / "scripts" / "generate_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verify(conn, log, gt_rows, project_id="demo"):
    """-> (строки отчёта, список проблем). log = Generator.log, gt_rows = строки ground_truth.csv."""
    report, problems = [], []
    items = conn.execute(
        "SELECT i.*, e.kind_hint, e.name_norm FROM items i JOIN staging_items_ext e USING(item_id) WHERE i.project_id = ?",
        (project_id,)).fetchall()
    by_key = {(r["source_file"], r["source_sheet"], r["source_row"]): r for r in items}

    # 1. файл за файлом
    report.append("1. Строки по файлам (в базе / по журналу генератора):")
    for file in sorted({r["file"] for r in log}):
        ref = {r["row"]: r for r in log if r["file"] == file}
        got = {k[2]: v for k, v in by_key.items() if k[0] == file}
        missing, extra = sorted(set(ref) - set(got)), sorted(set(got) - set(ref))
        bad_values = []
        for row in set(ref) & set(got):
            a, b = ref[row], got[row]
            if abs(b["quantity"] - a["qty_norm"]) > TOL:
                bad_values.append(f"{file}:{row} количество {b['quantity']} вместо {a['qty_norm']}")
            if (a["price_norm"] is None) != (b["unit_price"] is None) or (
                    a["price_norm"] is not None and abs(b["unit_price"] - a["price_norm"]) > TOL):
                bad_values.append(f"{file}:{row} цена {b['unit_price']} вместо {a['price_norm']}")
            if a["amount"] is not None and (b["amount"] is None or abs(b["amount"] - a["amount"]) > 0.005):
                bad_values.append(f"{file}:{row} сумма {b['amount']} вместо {a['amount']}")
        sheets = {k[1] for k in by_key if k[0] == file}
        ok = not (missing or extra or bad_values) and sheets == {ref[next(iter(ref))]["sheet"]}
        report.append(f"   {file:<14}{len(got):>4} / {len(ref):<4}{'ok' if ok else 'РАСХОЖДЕНИЕ'}")
        problems += [f"{file}: нет строк в items {missing}" for _ in [0] if missing]
        problems += [f"{file}: лишние строки в items {extra}" for _ in [0] if extra]
        problems += bad_values
    contract = conn.execute("SELECT * FROM items WHERE doc_type = 'contract' AND project_id = ?", (project_id,)).fetchall()
    report.append(f"   contract.xlsx{len(contract):>5} / 1   (договор одной строкой, в журнале генератора его нет)")
    if len(contract) != 1:
        problems.append("договор должен быть одной строкой в items")

    # 2. related_rows из ground_truth.csv
    date_rows = {r["file_name"]: r["date_source_row"] for r in conn.execute(
        "SELECT d.file_name, s.date_source_row FROM documents d JOIN staging_documents_ext s USING(doc_id) "
        "WHERE d.project_id = ?", (project_id,))}
    total, not_found = 0, []
    for g in gt_rows:
        for ref in g["related_rows"].split(";"):
            file, sheet, row = ref.split(":")
            total += 1
            if g["issue_type"] == "late_act":
                found = date_rows.get(file) == int(row)
            else:
                found = (file, sheet, int(row)) in by_key
            if not found:
                not_found.append(f"GT-{g['gt_id']} {ref}")
    report.append(f"2. Строки related_rows из ground_truth.csv: найдено {total - len(not_found)} из {total}")
    report.extend(f"   НЕ НАЙДЕНО: {x}" for x in not_found)
    problems += [f"related_rows не найдена: {x}" for x in not_found]

    # 3. суммы ВОР-2 после множителей
    vor2 = [r for r in items if r["source_file"] == "vor_2.xlsx"]
    report.append("3. ВОР-2, количество после множителя (работа / материал):")
    for label, prefix, expect, unit in (("кабель", "кабель", 2400, "m"), ("светильники", "светильники", 210, "pcs"),
                                        ("радиаторы", "радиаторы", 48, "pcs"), ("трубы", "труб", 650, "m")):
        rows = [r for r in vor2 if r["name_norm"].startswith(prefix) or (
            prefix == "труб" and r["name_norm"].startswith("прокладка трубопроводов"))
                or (prefix == "радиаторы" and r["name_norm"].startswith("установка радиаторов"))]
        qty = sorted((r["kind_hint"], r["quantity"], r["unit_norm"]) for r in rows)
        ok = len(rows) == 2 and all(q == expect and u == unit for _, q, u in qty)
        report.append(f"   {label:<12}{qty}  {'ok' if ok else 'РАСХОЖДЕНИЕ'}")
        if not ok:
            problems.append(f"ВОР-2 {label}: {qty}, ожидали {expect} {unit}")
    waste = [r["quantity"] for r in vor2 if r["name_norm"] == "строительный мусор"]
    report.append(f"   мусор       {waste} сумма {sum(waste):.1f}  {'ok' if abs(sum(waste) - 36.1) < 1e-9 else 'РАСХОЖДЕНИЕ'}")
    if abs(sum(waste) - 36.1) > 1e-9:
        problems.append(f"сумма мусора в ВОР-2 {sum(waste)}")

    # 4. итог акта
    row = conn.execute(
        "SELECT s.total_amount, s.total_row, (SELECT SUM(amount) FROM items WHERE doc_id = d.doc_id) s_sum, "
        "(SELECT COUNT(*) FROM items WHERE doc_id = d.doc_id AND source_row = s.total_row) in_items "
        "FROM documents d JOIN staging_documents_ext s USING(doc_id) WHERE d.file_name = 'act_2.xlsx' AND d.project_id = ?",
        (project_id,)).fetchone()
    ok = row and abs(row["total_amount"] - 6485749.6) < 0.005 and row["in_items"] == 0 and abs(row["s_sum"] - row["total_amount"]) < 0.01
    report.append(f"4. Итог act_2: {row['total_amount']} (строка {row['total_row']}), сумма строк {row['s_sum']:.2f}, "
                  f"в items попал: {'да' if row['in_items'] else 'нет'}  {'ok' if ok else 'РАСХОЖДЕНИЕ'}")
    if not ok:
        problems.append("итог act_2 не сходится или попал в items")
    return report, problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Проверка точности ingestion")
    parser.add_argument("--db", default=str(ROOT / "data" / "cache" / "demo.db"))
    parser.add_argument("--project", default="demo")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        generated = load_generator().generate(out_dir=tmp, meta_dir=tmp)
        gt_rows = list(csv.DictReader(open(Path(tmp) / "ground_truth.csv", encoding="utf-8")))
        conn = get_connection(args.db)
        report, problems = verify(conn, generated.log, gt_rows, args.project)
        conn.close()
    print("\n".join(report))
    print("\nИТОГ: " + ("всё сходится" if not problems else f"{len(problems)} расхождений:"))
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
