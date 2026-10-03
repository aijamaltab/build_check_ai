"""SQLite: схема из CLAUDE.md, раздел 7. Не менять без обсуждения в команде."""
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path("data") / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    doc_type    TEXT NOT NULL CHECK (doc_type IN ('vor','estimate','contract','act')),
    file_name   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('loaded','parsed','error')),
    parsed_at   TEXT
);

CREATE TABLE IF NOT EXISTS items (
    item_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     TEXT NOT NULL,
    doc_id         INTEGER NOT NULL REFERENCES documents(doc_id),
    doc_type       TEXT NOT NULL CHECK (doc_type IN ('vor','estimate','contract','act')),
    work_name_raw  TEXT,
    work_key       TEXT,
    unit_raw       TEXT,
    unit_norm      TEXT,
    quantity       REAL,
    unit_price     REAL,
    amount         REAL,
    doc_date       TEXT,
    source_file    TEXT NOT NULL,
    source_sheet   TEXT NOT NULL,
    source_row     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    match_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    work_key            TEXT,
    item_id             INTEGER NOT NULL REFERENCES items(item_id),
    matched_to_item_id  INTEGER REFERENCES items(item_id),
    score               REAL,
    method              TEXT NOT NULL CHECK (method IN ('exact','fuzzy','llm'))
);

CREATE TABLE IF NOT EXISTS issues (
    issue_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id   TEXT NOT NULL,
    work_key     TEXT,
    issue_type   TEXT NOT NULL CHECK (issue_type IN
                 ('volume_exceeded','price_increase','missing_in_vor','late_act')),
    expected     REAL,
    actual       REAL,
    delta        REAL,
    delta_pct    REAL,
    severity     TEXT,
    source_file  TEXT NOT NULL,
    source_row   INTEGER NOT NULL,
    explanation  TEXT
);

CREATE TABLE IF NOT EXISTS dq_checks (
    check_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      INTEGER NOT NULL REFERENCES documents(doc_id),
    check_name  TEXT NOT NULL,
    passed      INTEGER NOT NULL CHECK (passed IN (0,1)),
    details     TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    n_items      INTEGER,
    n_issues     INTEGER,
    mode         TEXT NOT NULL CHECK (mode IN ('llm','rules_only'))
);
"""


def get_connection(db_path=DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Открывает соединение; ":memory:" тоже подходит (для тестов)."""
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Создаёт все таблицы, если их ещё нет."""
    conn.executescript(SCHEMA)
    conn.commit()
