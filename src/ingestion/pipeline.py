"""Файл -> documents + items (marts) + staging-таблицы + dq_checks.

Слои: raw = путь и хеш файла (staging_documents_ext), staging = staging_items_ext, marts = items.
Схема CLAUDE.md §7 и src/db.py не меняются: согласованные поля (quantity_raw, kind_hint, currency, name_norm)
живут в отдельных staging-таблицах, пока напарница не решит вопрос (docs/schema_change_proposal.md).
"""
import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from src.db import init_db
from src.normalize import UnitNormalizer
from src.quality import run_checks

from .items import build_items
from .parse import parse_workbook

STAGING_SCHEMA = """
CREATE TABLE IF NOT EXISTS staging_items_ext (
    item_id          INTEGER PRIMARY KEY REFERENCES items(item_id),
    quantity_raw     TEXT,
    kind_hint        TEXT,
    name_norm        TEXT,
    currency         TEXT,
    unit_factor      REAL,
    formula_raw      TEXT,
    drawing_ref      TEXT,
    seq              TEXT,
    price_is_formula INTEGER
);
CREATE TABLE IF NOT EXISTS staging_documents_ext (
    doc_id          INTEGER PRIMARY KEY REFERENCES documents(doc_id),
    file_path       TEXT,
    sha256          TEXT,
    template        TEXT,
    currency        TEXT,
    date_source_row INTEGER,
    total_amount    REAL,
    total_row       INTEGER,
    n_rows_read     INTEGER,
    n_unrecognized  INTEGER,
    n_service       INTEGER
);
"""


@dataclass
class FileReport:
    file: str
    doc_type: str | None = None
    template: str | None = None
    status: str = "error"
    rows_read: int = 0
    unrecognized: list = field(default_factory=list)   # (строка, причина)
    dq_failed: list = field(default_factory=list)      # (check_name, details)
    error: str = ""


def init_staging(conn) -> None:
    init_db(conn)
    conn.executescript(STAGING_SCHEMA)
    conn.commit()


def reset_project(conn, project_id: str) -> None:
    """Повторный запуск не дублирует данные: стираем прошлую загрузку проекта (в порядке внешних ключей)."""
    items = "SELECT item_id FROM items WHERE project_id = ?"
    docs = "SELECT doc_id FROM documents WHERE project_id = ?"
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    # таблицы matching (src/matching/store.py) создаются позже и ссылаются на items и matches: чистим их первыми
    if "staging_matches_ext" in existing:
        conn.execute(f"DELETE FROM staging_matches_ext WHERE match_id IN "
                     f"(SELECT match_id FROM matches WHERE item_id IN ({items}))", (project_id,))
    if "staging_match_rows" in existing:
        conn.execute(f"DELETE FROM staging_match_rows WHERE item_id IN ({items})", (project_id,))
    for table in ("staging_match_groups", "staging_match_candidates", "staging_match_run"):
        if table in existing:
            conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
    conn.execute(f"DELETE FROM matches WHERE item_id IN ({items})", (project_id,))
    conn.execute("DELETE FROM issues WHERE project_id = ?", (project_id,))
    conn.execute(f"DELETE FROM staging_items_ext WHERE item_id IN ({items})", (project_id,))
    conn.execute("DELETE FROM items WHERE project_id = ?", (project_id,))
    conn.execute(f"DELETE FROM dq_checks WHERE doc_id IN ({docs})", (project_id,))
    conn.execute(f"DELETE FROM staging_documents_ext WHERE doc_id IN ({docs})", (project_id,))
    conn.execute("DELETE FROM documents WHERE project_id = ?", (project_id,))


def ingest_file(conn, path, project_id: str, cfg: dict, units: UnitNormalizer | None = None) -> FileReport:
    path = Path(path)
    report = FileReport(file=path.name)
    data = path.read_bytes()
    try:
        doc = parse_workbook(path, path.name, cfg)
    except Exception as exc:                         # битый файл не должен ронять весь прогон
        report.error = f"файл не открылся: {exc}"
        return report
    report.doc_type, report.template = doc.doc_type, doc.template
    if doc.doc_type is None:                         # тип неизвестен: в documents записать нельзя (CHECK по doc_type)
        report.error = "; ".join(doc.errors)
        return report
    items = build_items(doc, cfg, units)
    checks = run_checks(doc, items, cfg)
    failed = [c for c in checks if not c.passed]
    report.status = "error" if failed else "parsed"
    report.rows_read, report.unrecognized = len(items), list(doc.unrecognized)
    report.dq_failed = [(c.check_name, c.details) for c in failed]

    now = dt.datetime.now().isoformat(timespec="seconds")
    doc_id = conn.execute(
        "INSERT INTO documents (project_id, doc_type, file_name, status, parsed_at) VALUES (?,?,?,?,?)",
        (project_id, doc.doc_type, path.name, report.status, now)).lastrowid
    conn.execute(
        "INSERT INTO staging_documents_ext VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (doc_id, str(path), hashlib.sha256(data).hexdigest(), doc.template, doc.currency, doc.date_row,
         doc.total_amount, doc.total_row, len(items), len(doc.unrecognized), doc.n_service))
    for it in items:
        item_id = conn.execute(
            "INSERT INTO items (project_id, doc_id, doc_type, work_name_raw, work_key, unit_raw, unit_norm, quantity,"
            " unit_price, amount, doc_date, source_file, source_sheet, source_row) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, doc_id, doc.doc_type, it.work_name_raw, it.work_key, it.unit_raw, it.unit_norm, it.quantity,
             it.unit_price, it.amount, it.doc_date, path.name, doc.sheet, it.source_row)).lastrowid
        conn.execute(
            "INSERT INTO staging_items_ext VALUES (?,?,?,?,?,?,?,?,?,?)",
            (item_id, it.quantity_raw, it.kind_hint, it.name_norm, it.currency, it.unit_factor, it.formula_raw,
             it.drawing_ref, it.seq, int(it.price_is_formula)))
    for c in checks:
        conn.execute("INSERT INTO dq_checks (doc_id, check_name, passed, details) VALUES (?,?,?,?)",
                     (doc_id, c.check_name, int(c.passed), c.details))
    return report


def ingest_dir(conn, folder, project_id: str, cfg: dict) -> list:
    """Все .xlsx папки по алфавиту -> items. Прошлая загрузка проекта стирается."""
    init_staging(conn)
    reset_project(conn, project_id)
    units = UnitNormalizer(cfg["units"])
    reports = [ingest_file(conn, p, project_id, cfg, units) for p in sorted(Path(folder).glob("*.xlsx"))]
    conn.commit()
    return reports
