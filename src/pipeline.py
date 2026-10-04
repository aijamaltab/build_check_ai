"""Сквозной прогон: папка с Excel -> items -> matching -> (ИИ-шаги) -> проверки -> views -> сводка.

Приложение (Streamlit) вызывает только run_pipeline() и читает views position_status, issues_view и run_summary.
Режимы (docs/synthetic_spec.md §10, CLAUDE.md §3): llm (судья пар и/или RowMatcher подключены и доступны) и rules_only
(запасной режим, в интерфейсе баннер). Если запрошен llm, а ИИ недоступен, прогон идёт как rules_only с баннером.
Реального LLM здесь нет: судьи приходят снаружи (PairJudge, RowMatcher), в тестах это фейковые судьи.
Повторный запуск не дублирует данные: ingest_dir стирает прошлую загрузку проекта, matching и проверки пересчитываются.
"""
import datetime as dt
import json

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.matching import (NoopJudge, NoopRowMatcher, compute_matching, load_rows, resolve_candidates, resolve_rows,
                          save_matching)
from src.matching.store import summary_counts
from src.rules import create_views, fmt, run_checks

RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS staging_runs_ext (
    run_id          INTEGER PRIMARY KEY REFERENCES runs(run_id),
    project_id      TEXT,
    requested_mode  TEXT,
    banner          TEXT,
    threshold       REAL,
    use_synonyms    INTEGER,
    judge_label     TEXT,
    summary_json    TEXT,
    summary_text    TEXT
);
"""


def _label(obj, default):
    return type(obj).__name__ if obj is not None else default


def run_pipeline(source_dir, db_path, mode: str = "rules_only", judge=None, row_matcher=None, *, use_synonyms: bool = True,
                 threshold: float | None = None, project_id: str = "demo", cfg: dict | None = None) -> dict:
    """-> сводка (словарь). judge: PairJudge, row_matcher: RowMatcher (оба необязательны)."""
    cfg = cfg or load_config()
    rules = cfg["rules"]
    if mode not in rules["llm"]["modes"]:
        raise ValueError(f"режим {mode!r} не из {rules['llm']['modes']}")
    started = dt.datetime.now().isoformat(timespec="seconds")
    conn = get_connection(db_path)
    try:
        ingest_reports = ingest_dir(conn, source_dir, project_id, cfg)
        ai_available = mode == "llm" and any(getattr(x, "available", False) for x in (judge, row_matcher) if x is not None)
        effective = "llm" if ai_available else "rules_only"
        banner = None if effective == "llm" else rules["llm"]["rules_only_banner"]

        result = compute_matching(load_rows(conn, project_id), cfg, use_synonyms, threshold)
        save_matching(conn, result, project_id, cfg, effective)
        ai = {"pairs_asked": 0, "pairs_accepted": 0, "rows_asked": 0, "rows_accepted": 0, "rows_none": 0, "rows_rejected": 0}
        if effective == "llm":
            if judge is not None:
                stats = resolve_candidates(conn, judge, cfg, project_id)
                ai["pairs_asked"], ai["pairs_accepted"] = stats.asked, stats.accepted
            if row_matcher is not None:
                stats = resolve_rows(conn, row_matcher, cfg, project_id)
                ai.update(rows_asked=stats.asked, rows_accepted=stats.accepted, rows_none=stats.none, rows_rejected=stats.rejected)
        checks = run_checks(conn, cfg, project_id, effective)
        create_views(conn, cfg)

        counts = summary_counts(conn, project_id)
        counts["l"] = checks.incomparable_rows                       # «не сопоставимо»: валюты не совпали, цена не проверена
        statuses = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) n FROM position_status WHERE project_id = ? GROUP BY status", (project_id,))}
        summary = {
            "mode": effective, "requested_mode": mode, "banner": banner, "n": counts["n"], "m": counts["m"], "k": counts["k"],
            "a": counts["a"], "l": counts["l"], "z": checks.n_issues, "impact_som": round(checks.impact_total, 2),
            "by_type": checks.counts, "statuses": {s: statuses.get(s, 0) for s in ("red", "yellow", "green")},
            "threshold": result.threshold, "use_synonyms": use_synonyms, "ai": ai,
            "documents_with_errors": [r.file for r in ingest_reports if r.status == "error"],
            "files": len(ingest_reports),
        }
        summary["caveat"] = (rules["issues"]["rules_only_status_caveat"].format(a=summary["a"])
                             if effective == "rules_only" and summary["a"] else None)
        summary["text"] = rules["issues"]["summary_run_template"].format(
            n=summary["n"], m=summary["m"], k=summary["k"], a=summary["a"], l=summary["l"], z=summary["z"],
            impact=fmt(summary["impact_som"]), mode=effective)
        run_id = conn.execute("INSERT INTO runs (started_at, finished_at, n_items, n_issues, mode) VALUES (?,?,?,?,?)",
                              (started, dt.datetime.now().isoformat(timespec="seconds"), counts["n"], checks.n_issues, effective)).lastrowid
        conn.executescript(RUNS_SCHEMA)
        conn.execute("INSERT INTO staging_runs_ext VALUES (?,?,?,?,?,?,?,?,?)",
                     (run_id, project_id, mode, banner, result.threshold, int(use_synonyms),
                      f"{_label(judge, '-')}+{_label(row_matcher, '-')}", json.dumps(summary, ensure_ascii=False), summary["text"]))
        conn.executescript("""
DROP VIEW IF EXISTS run_summary;
CREATE VIEW run_summary AS
SELECT r.run_id, x.project_id, r.started_at, r.finished_at, r.n_items, r.n_issues, r.mode, x.requested_mode, x.banner,
       x.summary_text, x.summary_json
FROM runs r JOIN staging_runs_ext x ON x.run_id = r.run_id
ORDER BY r.run_id DESC;
""")
        conn.commit()
        summary["run_id"] = run_id
        return summary
    finally:
        conn.close()
