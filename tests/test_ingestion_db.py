"""Загрузка в SQLite, dq-проверки и скрипт сверки точности."""
import csv
import importlib.util
import io
from pathlib import Path

import pytest
from openpyxl import Workbook

from src.config import load_config
from src.db import get_connection
from src.ingestion import build_items, ingest_dir, ingest_file, init_staging, parse_workbook
from src.quality import run_checks
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()

spec = importlib.util.spec_from_file_location("verify_ingestion", ROOT / "scripts" / "verify_ingestion.py")
verify_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_mod)

ITEMS_COLUMNS = ["item_id", "project_id", "doc_id", "doc_type", "work_name_raw", "work_key", "unit_raw", "unit_norm",
                 "quantity", "unit_price", "amount", "doc_date", "source_file", "source_sheet", "source_row"]


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    g = gen.generate(out_dir=out, meta_dir=out)
    conn = get_connection(":memory:")
    reports = ingest_dir(conn, out, "demo", CFG)
    gt = list(csv.DictReader(open(out / "ground_truth.csv", encoding="utf-8")))
    return conn, reports, g, gt, out


def test_schema_of_items_is_the_contract(loaded):
    conn = loaded[0]
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(items)")]
    assert cols == ITEMS_COLUMNS                                   # §7 не менялся
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"documents", "items", "matches", "issues", "dq_checks", "runs"} <= tables
    assert {"staging_items_ext", "staging_documents_ext"} <= tables


def test_all_files_parsed_without_dq_failures(loaded):
    conn, reports, *_ = loaded
    assert [r.status for r in reports] == ["parsed"] * 9
    assert all(not r.unrecognized and not r.dq_failed for r in reports)
    counts = dict(conn.execute("SELECT doc_type, COUNT(*) FROM items GROUP BY doc_type").fetchall())
    assert counts == {"act": 80, "contract": 1, "estimate": 50, "vor": 50}


def test_raw_layer_stores_path_and_hash(loaded):
    conn = loaded[0]
    rows = conn.execute("SELECT file_path, sha256 FROM staging_documents_ext").fetchall()
    assert len(rows) == 9 and all(len(r["sha256"]) == 64 and r["file_path"].endswith(".xlsx") for r in rows)


def test_staging_keeps_raw_quantity_and_kind(loaded):
    conn = loaded[0]
    row = conn.execute(
        "SELECT i.quantity, i.unit_raw, e.quantity_raw, e.kind_hint, e.unit_factor FROM items i JOIN staging_items_ext e "
        "USING(item_id) WHERE i.source_file = 'vor_2.xlsx' AND i.work_name_raw LIKE 'Светильники LED монтаж%'").fetchone()
    assert (row["quantity"], row["unit_raw"], row["quantity_raw"], row["kind_hint"], row["unit_factor"]) == (
        210, "100 шт.", "2.1", "work", 100)


def test_every_item_has_source_file_sheet_row(loaded):
    conn = loaded[0]
    assert conn.execute("SELECT COUNT(*) FROM items WHERE source_file = '' OR source_sheet = '' OR source_row < 1").fetchone()[0] == 0


def test_rerun_does_not_duplicate(loaded):
    conn, _, _, _, out = loaded
    ingest_dir(conn, out, "demo", CFG)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 181
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 9


def test_verify_script_confirms_accuracy(loaded):
    conn, _, g, gt, _ = loaded
    report, problems = verify_mod.verify(conn, g.log, gt)
    assert problems == [], "\n".join(report)


def test_verify_script_notices_damage(tmp_path_factory, loaded):
    """Сверка не должна быть формальной: если испортить базу, она обязана это заметить."""
    _, _, g, gt, out = loaded
    conn = get_connection(":memory:")
    ingest_dir(conn, out, "demo", CFG)
    conn.execute("UPDATE items SET quantity = quantity + 1 WHERE source_file = 'act_1.xlsx' AND source_row = 7")
    file, _, row = gt[0]["related_rows"].split(";")[0].split(":")      # строка из related_rows GT-1
    victim = "SELECT item_id FROM items WHERE source_file = ? AND source_row = ?"
    conn.execute(f"DELETE FROM staging_items_ext WHERE item_id IN ({victim})", (file, int(row)))
    assert conn.execute("DELETE FROM items WHERE source_file = ? AND source_row = ?", (file, int(row))).rowcount == 1
    _, problems = verify_mod.verify(conn, g.log, gt)
    assert any("количество" in p for p in problems) and any("related_rows" in p for p in problems)


# ---------- dq: негативные случаи на маленьких книгах ----------
def book(rows, total=None):
    """ВОР (каркас А) из списка (название, единица, количество, формула)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "ВОР"
    ws.append(["№ п.п", "Наименование работ и затрат", "Ед. изм.", "Кол-во", "Формула расчёта объёма"])
    for i, (name, unit, qty, formula) in enumerate(rows, 1):
        ws.append([i, name, unit, qty, formula])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def dq(rows):
    doc = parse_workbook(book(rows), "t.xlsx", CFG)
    return {c.check_name: c for c in run_checks(doc, build_items(doc, CFG), CFG)}


def test_dq_all_pass_on_clean_book():
    assert all(c.passed for c in dq([("Работа А", "м2", 10, None), ("Работа Б", "шт", 3, None)]).values())


def test_dq_negative_quantity():
    assert not dq([("Работа А", "м2", -5, None)])["количество не отрицательное"].passed


def test_dq_unknown_unit():
    c = dq([("Работа А", "парсек", 5, None)])["единица известна"]
    assert not c.passed and "парсек" in c.details


def test_dq_full_duplicate_fails_but_repeated_name_with_other_quantity_does_not():
    dup = dq([("Работа А", "м2", 10, "по смете: 10"), ("Работа А", "м2", 10, "по смете: 10")])
    assert not dup["нет полных дублей строк"].passed
    same_name = dq([("Строительный мусор", "т", 12.5, None), ("Строительный мусор", "т", 8, None)])
    assert same_name["нет полных дублей строк"].passed


def test_dq_unrecognized_share_and_failed_file_gets_error_status(tmp_path):
    rows = [("Работа А", "м2", "много", None), ("Работа Б", "м2", "сколько-то", None), ("Работа В", "м2", 3, None)]
    assert not dq(rows)["доля нераспознанных строк"].passed
    path = tmp_path / "bad.xlsx"
    path.write_bytes(book(rows).getvalue())
    conn = get_connection(":memory:")
    init_staging(conn)
    report = ingest_file(conn, path, "demo", CFG)
    assert report.status == "error" and len(report.unrecognized) == 2
    assert conn.execute("SELECT status FROM documents").fetchone()["status"] == "error"
    assert conn.execute("SELECT COUNT(*) FROM dq_checks WHERE passed = 0").fetchone()[0] >= 1


def test_dq_sum_must_match_total():
    wb = Workbook()
    ws = wb.active
    ws.append(["№ поз.", "Шифр норматива", "Наименование", "Ед. изм.", "Кол-во", "Стоимость единицы, сом", "Общая стоимость, сом"])
    ws.append([1, None, "Работа А", "м2", 10, 100, 1000])
    ws.append([2, None, "Работа Б", "м2", 5, 100, 500])
    ws.append([None, None, "Итого по смете, сом", None, None, None, 9999])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    doc = parse_workbook(buf, "e.xlsx", CFG)
    checks = {c.check_name: c for c in run_checks(doc, build_items(doc, CFG), CFG)}
    assert not checks["сумма строк равна итогу"].passed and len(doc.rows) == 2
