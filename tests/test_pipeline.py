"""run_pipeline: единая точка входа для приложения (режимы, сводка, runs, повторный запуск)."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from src.config import load_config
from src.db import get_connection
from src.pipeline import run_pipeline
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()
sys.path.insert(0, str(ROOT / "scripts"))
import verify_matching as vm  # noqa: E402


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    generated = gen.generate(out_dir=out, meta_dir=out)
    return out, {(r["file"], r["row"]): r["item_no"] for r in generated.log}


def q(db, sql, *args):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_llm_mode_with_perfect_fake_ai_finds_everything(synth, tmp_path):
    out, truth = synth
    s = run_pipeline(out, tmp_path / "a.db", "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth))
    assert s["mode"] == "llm" and s["requested_mode"] == "llm" and s["banner"] is None
    assert (s["n"], s["m"], s["k"], s["a"], s["l"], s["z"]) == (180, 0, 2, 0, 0, 12)
    assert s["by_type"] == {"volume_exceeded": 5, "price_increase": 3, "missing_in_vor": 2, "late_act": 2}
    assert s["statuses"] == {"red": 10, "yellow": 6, "green": 31}
    assert s["impact_som"] == 1282000.0                                         # сумма expected_impact_som из ground_truth.csv
    assert s["ai"]["rows_accepted"] > 0 and s["ai"]["pairs_accepted"] > 0
    assert "режим llm" in s["text"] and "расхождений 12" in s["text"] and "возможное влияние на бюджет 1 282 000 сом" in s["text"]


def test_rules_only_mode_has_banner_and_flags_ambiguous(synth, tmp_path):
    s = run_pipeline(synth[0], tmp_path / "b.db", "rules_only")
    assert s["mode"] == "rules_only" and s["banner"] == CFG["rules"]["llm"]["rules_only_banner"]
    assert s["a"] > 0 and s["k"] >= s["a"] and s["z"] > 0 and s["ai"]["rows_asked"] == 0
    assert "режим rules_only" in s["text"] and "требует проверки" in s["text"]
    # missing_in_vor без ИИ: низкая уверенность, severity не высокая
    rows = q(tmp_path / "b.db", "SELECT severity, confidence FROM issues_view WHERE issue_type = 'missing_in_vor'")
    assert rows and all(sev != "high" and conf == "low" for sev, conf in rows)


def test_llm_requested_without_ai_falls_back_with_banner(synth, tmp_path):
    from src.matching import NoopJudge, NoopRowMatcher
    for kw in ({}, {"judge": NoopJudge(), "row_matcher": NoopRowMatcher()}):
        s = run_pipeline(synth[0], tmp_path / "c.db", "llm", **kw)
        assert s["mode"] == "rules_only" and s["requested_mode"] == "llm" and "недоступен" in s["banner"]
        assert q(tmp_path / "c.db", "SELECT mode FROM runs ORDER BY run_id DESC LIMIT 1") == [("rules_only",)]


def test_modes_differ_in_what_they_find(synth, tmp_path):
    out, truth = synth
    plain = run_pipeline(out, tmp_path / "d1.db", "rules_only")
    ai = run_pipeline(out, tmp_path / "d2.db", "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth))
    assert ai["z"] == 12 and plain["by_type"]["missing_in_vor"] > ai["by_type"]["missing_in_vor"]
    assert plain["by_type"]["volume_exceeded"] < ai["by_type"]["volume_exceeded"]


def test_rerun_does_not_duplicate_and_does_not_fail(synth, tmp_path):
    out, truth = synth
    db = tmp_path / "e.db"
    first = run_pipeline(out, db, "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth))
    snapshot = [q(db, f"SELECT COUNT(*) FROM {t}") for t in ("items", "documents", "matches", "issues", "staging_issues_ext", "dq_checks")]
    second = run_pipeline(out, db, "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth))
    assert snapshot == [q(db, f"SELECT COUNT(*) FROM {t}") for t in ("items", "documents", "matches", "issues", "staging_issues_ext", "dq_checks")]
    assert {k: v for k, v in first.items() if k != "run_id"} == {k: v for k, v in second.items() if k != "run_id"}
    # переключение режима на том же файле БД тоже не ломается и не оставляет следов ИИ
    third = run_pipeline(out, db, "rules_only")
    assert third["mode"] == "rules_only" and q(db, "SELECT COUNT(*) FROM matches WHERE method = 'llm'") == [(0,)]
    assert q(db, "SELECT COUNT(*) FROM runs") == [(3,)]


def test_runs_table_and_run_summary_view(synth, tmp_path):
    out, truth = synth
    db = tmp_path / "f.db"
    run_pipeline(out, db, "rules_only")
    s = run_pipeline(out, db, "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth))
    rows = q(db, "SELECT run_id, started_at, finished_at, n_items, n_issues, mode FROM runs ORDER BY run_id")
    assert [r[5] for r in rows] == ["rules_only", "llm"] and rows[1][3:5] == (180, 12) and rows[1][1] <= rows[1][2]
    last = q(db, "SELECT run_id, mode, requested_mode, banner, summary_text, summary_json FROM run_summary LIMIT 1")[0]
    assert last[0] == s["run_id"] and last[1] == "llm" and last[3] is None and last[4] == s["text"]
    assert json.loads(last[5])["z"] == 12


def test_app_needs_only_the_pipeline_call_and_views(synth, tmp_path):
    db = tmp_path / "g.db"
    run_pipeline(synth[0], db, "rules_only")
    conn = get_connection(db)
    assert conn.execute("SELECT COUNT(*) FROM position_status").fetchone()[0] > 0
    row = conn.execute("SELECT * FROM issues_view LIMIT 1").fetchone()
    assert row["source_file"] and row["source_sheet"] and row["source_row"] and row["explanation"]


def test_invalid_mode_and_empty_folder(tmp_path):
    with pytest.raises(ValueError):
        run_pipeline(tmp_path, tmp_path / "x.db", "turbo")
    (tmp_path / "empty").mkdir()
    s = run_pipeline(tmp_path / "empty", tmp_path / "y.db", "rules_only")
    assert (s["n"], s["z"], s["files"]) == (0, 0, 0)


def test_documents_with_dq_errors_are_reported(tmp_path):
    """Файл, не прошедший dq (отрицательное количество), помечается в сводке и не участвует молча."""
    from tests.project_factory import make_project
    make_project(tmp_path / "p", [("Кладка стен", "м3", 100)], [("Кладка стен", "м3", 100, 10)], [[("Кладка стен", "м3", -5, 10)]])
    s = run_pipeline(tmp_path / "p", tmp_path / "z.db", "rules_only")
    assert s["documents_with_errors"] == ["act_1.xlsx"]
