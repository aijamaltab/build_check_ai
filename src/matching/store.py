"""Запись результата matching в SQLite.

Контракт §7 не меняется: matches(match_id, work_key, item_id, matched_to_item_id, score, method) пишется как есть,
а stage (exact / synonyms / fuzzy / llm), kind, reason и confidence лежат в staging_matches_ext.
Кандидаты для LLM, группы строк и параметры прогона тоже в staging. Окончательный work_key (ключ строки ВОР)
записывается в items.work_key всем строкам: сопоставленным, ВОР и несопоставленным (у последних свой ключ).
"""
import datetime as dt

from .matcher import MatchResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS staging_match_run (
    project_id    TEXT PRIMARY KEY,
    use_synonyms  INTEGER,
    threshold     REAL,
    missing_side  TEXT,
    mode          TEXT,
    created_at    TEXT
);
CREATE TABLE IF NOT EXISTS staging_match_groups (
    group_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id       TEXT,
    doc_id           INTEGER,
    doc_type         TEXT,
    name             TEXT,
    unit_norm        TEXT,
    signal           TEXT,
    kind             TEXT,
    qty_sum          REAL,
    n_rows           INTEGER,
    first_item_id    INTEGER,
    status           TEXT,
    final_work_key   TEXT,
    matched_group_id INTEGER
);
CREATE TABLE IF NOT EXISTS staging_match_rows (
    item_id   INTEGER PRIMARY KEY REFERENCES items(item_id),
    group_id  INTEGER,
    counted   INTEGER
);
CREATE TABLE IF NOT EXISTS staging_matches_ext (
    match_id    INTEGER PRIMARY KEY REFERENCES matches(match_id),
    group_id    INTEGER,
    stage       TEXT,
    kind        TEXT,
    reason      TEXT,
    confidence  REAL
);
CREATE TABLE IF NOT EXISTS staging_match_candidates (
    candidate_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         TEXT,
    item_id            INTEGER,
    candidate_item_id  INTEGER,
    group_id           INTEGER,
    candidate_group_id INTEGER,
    score              REAL,
    reason_for_review  TEXT,
    status             TEXT DEFAULT 'open',
    judge_reason       TEXT,
    judge_confidence   REAL
);
"""

TABLES_BY_ITEM = ("staging_match_rows",)


def init_match_tables(conn) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def clear_matching(conn, project_id: str, cfg: dict) -> None:
    """Стирает прошлый результат matching проекта (идемпотентный перезапуск)."""
    items = "SELECT item_id FROM items WHERE project_id = ?"
    docs = "SELECT doc_id FROM documents WHERE project_id = ?"
    conn.execute(f"DELETE FROM staging_matches_ext WHERE match_id IN "
                 f"(SELECT match_id FROM matches WHERE item_id IN ({items}))", (project_id,))
    conn.execute(f"DELETE FROM matches WHERE item_id IN ({items})", (project_id,))
    conn.execute(f"DELETE FROM staging_match_rows WHERE item_id IN ({items})", (project_id,))
    for table in ("staging_match_groups", "staging_match_candidates", "staging_match_run"):
        conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
    conn.execute(f"DELETE FROM dq_checks WHERE check_name = ? AND doc_id IN ({docs})",
                 (cfg["rules"]["matching"]["kind_unknown_dq_check"], project_id))


def work_key(cfg: dict, kind: str, name: str, unit) -> str:
    return cfg["rules"]["matching"]["work_key_format"].format(kind=kind, name=name, unit=unit or "")


def refresh_kind_dq(conn, project_id: str, cfg: dict) -> None:
    """dq «kind не определён»: несопоставленные строки вне ВОР без признака получают work (диагностика, не расхождение)."""
    name = cfg["rules"]["matching"]["kind_unknown_dq_check"]
    docs = "SELECT doc_id FROM documents WHERE project_id = ?"
    conn.execute(f"DELETE FROM dq_checks WHERE check_name = ? AND doc_id IN ({docs})", (name, project_id))
    rows = conn.execute(
        "SELECT g.doc_id, i.source_row FROM staging_match_groups g JOIN staging_match_rows r ON r.group_id = g.group_id "
        "JOIN items i ON i.item_id = r.item_id WHERE g.project_id = ? AND g.doc_type != 'vor' AND g.status = 'unmatched' "
        "AND g.signal IS NULL ORDER BY g.doc_id, i.source_row", (project_id,)).fetchall()
    by_doc = {}
    for r in rows:
        by_doc.setdefault(r["doc_id"], []).append(r["source_row"])
    for doc_id, nums in by_doc.items():
        conn.execute("INSERT INTO dq_checks (doc_id, check_name, passed, details) VALUES (?,?,?,?)",
                     (doc_id, name, 0, f"строк: {len(nums)}; строки " + ", ".join(map(str, nums[:30]))))


def set_final_key(conn, group_id: int, key: str) -> None:
    conn.execute("UPDATE staging_match_groups SET final_work_key = ? WHERE group_id = ?", (key, group_id))
    conn.execute("UPDATE items SET work_key = ? WHERE item_id IN "
                 "(SELECT item_id FROM staging_match_rows WHERE group_id = ?)", (key, group_id))


def save_matching(conn, result: MatchResult, project_id: str, cfg: dict, mode: str = "rules_only") -> dict:
    """Пишет результат. -> {gid группы в памяти: group_id в БД}."""
    init_match_tables(conn)
    clear_matching(conn, project_id, cfg)
    default_kind = cfg["rules"]["matching"]["kind_unknown_default"]
    conn.execute("INSERT INTO staging_match_run VALUES (?,?,?,?,?,?)",
                 (project_id, int(result.use_synonyms), result.threshold, result.missing_side, mode,
                  dt.datetime.now().isoformat(timespec="seconds")))
    paired = {p.doc.gid: p for p in result.pairs}
    db_id = {}
    for g in result.groups:
        status = "vor" if g.is_vor else ("matched" if g.gid in paired else "unmatched")
        kind = g.kind if g.is_vor else (paired[g.gid].vor.kind if g.gid in paired else (g.kind or default_kind))
        db_id[g.gid] = conn.execute(
            "INSERT INTO staging_match_groups (project_id, doc_id, doc_type, name, unit_norm, signal, kind, qty_sum,"
            " n_rows, first_item_id, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (project_id, g.doc_id, g.doc_type, g.name, g.unit_norm, g.kind if not g.is_vor else None, kind, g.qty_sum,
             len(g.rows), g.first.item_id, status)).lastrowid
        for row in g.rows:
            conn.execute("INSERT INTO staging_match_rows VALUES (?,?,?)", (row.item_id, db_id[g.gid], g.counted[row.item_id]))
    for g in result.groups:
        if g.is_vor:
            set_final_key(conn, db_id[g.gid], work_key(cfg, g.kind, g.name, g.unit_norm))
    for p in result.pairs:
        key = work_key(cfg, p.vor.kind, p.vor.name, p.vor.unit_norm)
        for row in p.doc.rows:
            mid = conn.execute("INSERT INTO matches (work_key, item_id, matched_to_item_id, score, method) VALUES (?,?,?,?,?)",
                               (key, row.item_id, p.vor.first.item_id, p.score, p.method)).lastrowid
            conn.execute("INSERT INTO staging_matches_ext VALUES (?,?,?,?,?,?)",
                         (mid, db_id[p.doc.gid], p.stage, p.vor.kind, p.reason, p.confidence))
        conn.execute("UPDATE staging_match_groups SET matched_group_id = ? WHERE group_id = ?",
                     (db_id[p.vor.gid], db_id[p.doc.gid]))
        set_final_key(conn, db_id[p.doc.gid], key)
    for g in result.unmatched:
        kind = g.kind or default_kind
        set_final_key(conn, db_id[g.gid], work_key(cfg, kind, g.name, g.unit_norm))
    for c in result.candidates:
        conn.execute(
            "INSERT INTO staging_match_candidates (project_id, item_id, candidate_item_id, group_id, candidate_group_id,"
            " score, reason_for_review) VALUES (?,?,?,?,?,?,?)",
            (project_id, c.doc.first.item_id, c.vor.first.item_id, db_id[c.doc.gid], db_id[c.vor.gid], c.score, c.reason))
    refresh_kind_dq(conn, project_id, cfg)
    conn.commit()
    return db_id
