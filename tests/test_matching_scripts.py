"""Скрипты match.py и verify_matching.py: запуск и ключевые цифры."""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.matching import compute_matching, load_rows
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()

spec = importlib.util.spec_from_file_location("verify_matching", ROOT / "scripts" / "verify_matching.py")
vm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vm)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    base = tmp_path_factory.mktemp("matching_scripts")
    generated = gen.generate(out_dir=base / "files", meta_dir=base / "meta")
    db = base / "demo.db"
    conn = get_connection(db)
    ingest_dir(conn, base / "files", "demo", CFG)
    rows = load_rows(conn, "demo")
    conn.close()
    return {"db": db, "rows": rows, "truth": {(r["file"], r["row"]): r["item_no"] for r in generated.log}}


def test_match_script_prints_methods_candidates_unmatched_for_both_thresholds(prepared):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "match.py"), "--db", str(prepared["db"]), "--mode", "rules_only"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    for phrase in ("порог 85", "порог 90", "exact", "fuzzy", "llm", "в кандидатах для LLM", "не сопоставлено",
                   "Не сопоставлено (файл:лист:строка)", "act_3.xlsx:Акт:"):
        assert phrase in out, phrase
    conn = get_connection(prepared["db"])
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] > 0
    assert conn.execute("SELECT mode FROM staging_match_run").fetchone()[0] == "rules_only"


def test_match_script_llm_mode_uses_noop_judge(prepared):
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "match.py"), "--db", str(prepared["db"]), "--mode", "llm"],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    assert "NoopJudge" in out and "судья недоступен" in out


def test_match_script_without_items_fails_cleanly(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "match.py"), "--db", str(tmp_path / "empty.db")],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode != 0 or "items" in proc.stdout


def test_compare_metrics_add_up_and_show_known_false_merge(prepared):
    res = compute_matching(prepared["rows"], CFG, True, 90)
    m = vm.compare(res, prepared["truth"])
    assert m["rows"] == 130 == m["correct"] + m["wrong"] + m["true_missing"] + m["false_unmatched"]
    assert m["true_missing"] == 2                                            # отмостка и видеонаблюдение: пары в ВОР нет
    assert m["cand_right"] + m["cand_wrong"] + m["cand_none"] == m["false_unmatched"]
    assert m["wrong"] == 1 and m["wrong_pairs"][0][:2] == ("act_3.xlsx", 24)  # известная склейка материала кабеля
    assert m["vor_mixed"] == []                                              # внутри ВОР разные работы не слиплись


def test_synonyms_help_and_threshold_85_is_not_worse_than_90_on_false_merges(prepared):
    results = {(syn, th): vm.compare(compute_matching(prepared["rows"], CFG, syn, th), prepared["truth"])
               for syn in (False, True) for th in (85, 90)}
    assert results[(True, 90)]["correct"] > results[(False, 90)]["correct"]
    assert results[(True, 85)]["correct"] >= results[(True, 90)]["correct"]
    assert all(r["wrong"] <= 1 for r in results.values())


def test_reingest_after_matching_does_not_break_on_foreign_keys(prepared, tmp_path):
    """Повторная загрузка проекта после matching стирает и его staging-таблицы (регрессия: FOREIGN KEY failed)."""
    from src.matching import save_matching
    conn = get_connection(tmp_path / "again.db")
    files = prepared["db"].parent / "files"
    ingest_dir(conn, files, "demo", CFG)
    save_matching(conn, compute_matching(load_rows(conn, "demo"), CFG), "demo", CFG)
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] > 0
    ingest_dir(conn, files, "demo", CFG)
    for table in ("matches", "staging_matches_ext", "staging_match_groups", "staging_match_rows", "staging_match_candidates"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 181
