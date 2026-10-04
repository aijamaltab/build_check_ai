"""position_status (светофор) и issues_view: на синтетике сверка с data/expected_status.csv (потолок ИИ) и на малых проектах."""
import csv
import sqlite3
import sys
from pathlib import Path

import pytest

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.matching import compute_matching, load_rows, resolve_candidates, resolve_rows, save_matching
from src.rules import create_views, run_checks
from tests.project_factory import make_project
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()
sys.path.insert(0, str(ROOT / "scripts"))
import verify_matching as vm  # noqa: E402


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    generated = gen.generate(out_dir=out, meta_dir=out)
    truth = {(r["file"], r["row"]): r["item_no"] for r in generated.log}
    expected = {r["item_no"]: r for r in csv.DictReader(open(out / "expected_status.csv", encoding="utf-8"))}
    return {"dir": out, "truth": truth, "expected": expected}


def build(synth, llm):
    conn = get_connection(":memory:")
    ingest_dir(conn, synth["dir"], "demo", CFG)
    save_matching(conn, compute_matching(load_rows(conn, "demo"), CFG), "demo", CFG, "llm" if llm else "rules_only")
    if llm:
        resolve_candidates(conn, vm.TruthJudge(synth["truth"]), CFG, "demo")
        resolve_rows(conn, vm.TruthRowMatcher(synth["truth"]), CFG, "demo")
    run_checks(conn, CFG, "demo", "llm" if llm else "rules_only")
    create_views(conn, CFG)
    return conn


def item_of(conn, work_key, truth):
    """Номер позиции по эталону генератора для ключа (через строки, которые к нему привязаны)."""
    rows = conn.execute("SELECT i.source_file, i.source_row FROM items i WHERE i.work_key = ? AND i.doc_type IN ('vor', 'act')", (work_key,)).fetchall()
    found = {truth[(r["source_file"], r["source_row"])] for r in rows}
    assert len(found) == 1, (work_key, found)
    return found.pop()


def test_position_status_matches_expected_status_csv_with_perfect_ai(synth):
    """Потолок: с идеальным ИИ светофор совпадает с эталоном по всем 47 ключам: 10 красных, 6 жёлтых, 31 зелёный."""
    conn = build(synth, llm=True)
    rows = conn.execute("SELECT * FROM position_status WHERE project_id = 'demo'").fetchall()
    assert len(rows) == 47
    got = {item_of(conn, r["work_key"], synth["truth"]): r for r in rows}
    exp = synth["expected"]
    assert set(got) == set(exp)
    for item_no, r in got.items():
        assert r["status"] == exp[item_no]["expected_status"], (item_no, r["status"], r["pct"])
        assert r["fact_qty"] == pytest.approx(float(exp[item_no]["fact_qty"]))
        if exp[item_no]["plan_qty"]:
            assert r["plan_qty"] == pytest.approx(float(exp[item_no]["plan_qty"]))
        else:
            assert r["plan_qty"] is None and r["pct"] is None                    # позиции без ВОР
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("red", "yellow", "green")}
    assert counts == {"red": 10, "yellow": 6, "green": 31}
    assert all(r["review_rows"] == 0 for r in rows)


def test_position_status_rules_only_is_available_and_marks_rows_for_review(synth):
    conn = build(synth, llm=False)
    rows = conn.execute("SELECT * FROM position_status").fetchall()
    assert len(rows) > 47                                                      # absent-строки (в том числе ложные) стали позициями без плана
    assert sum(r["review_rows"] for r in rows) > 0                             # позиции, по которым есть ambiguous-строки
    assert {r["status"] for r in rows} <= {"red", "yellow", "green"}
    no_plan = [r for r in rows if r["plan_qty"] is None]
    assert no_plan and all(r["status"] == "red" for r in no_plan)


def test_issues_view_has_sheet_impact_and_sorted_by_impact(synth):
    conn = build(synth, llm=True)
    rows = conn.execute("SELECT * FROM issues_view").fetchall()
    assert len(rows) == 12
    assert {"source_file", "source_sheet", "source_row", "impact_som", "explanation", "severity", "work_key"} <= set(rows[0].keys())
    assert all(r["source_file"] and r["source_sheet"] and r["source_row"] for r in rows)
    impacts = [r["impact_som"] for r in rows]
    known = [x for x in impacts if x is not None]
    assert known == sorted(known, reverse=True)
    assert impacts[len(known):] == [None] * (len(impacts) - len(known))        # NULL (late_act) в конце
    assert known[0] == 240000                                                  # видеонаблюдение GT-10


def test_impact_equals_ground_truth_for_every_found_issue(synth):
    """Влияние на бюджет по формулам spec §7 равно expected_impact_som из ground_truth.csv."""
    conn = build(synth, llm=True)
    gt = list(csv.DictReader(open(synth["dir"] / "ground_truth.csv", encoding="utf-8")))
    view = conn.execute("SELECT * FROM issues_view").fetchall()
    for g in gt:
        if not g["expected_impact_som"]:
            continue
        related = {tuple(x.split(":")[:1]) + (int(x.split(":")[2]),) for x in g["related_rows"].split(";")}
        hits = [r for r in view if r["issue_type"] == g["issue_type"] and (r["source_file"], r["source_row"]) in related]
        assert hits, g["gt_id"]
        assert hits[0]["impact_som"] == pytest.approx(float(g["expected_impact_som"]), abs=0.01), g["gt_id"]


def test_small_project_traffic_light_boundaries(tmp_path):
    """Граница жёлтого: 94% жёлтый, 95% зелёный; 105% зелёный, 106% красный (volume_exceeded, допуск 5%)."""
    names = [f"Работа номер {c}" for c in "АБВГД"]
    facts = [94, 95, 100, 105, 106]
    make_project(tmp_path / "p", [(n, "м3", 100) for n in names], [(n, "м3", 100, 100) for n in names],
                 [[(n, "м3", f, 100) for n, f in zip(names, facts)]])
    conn = get_connection(":memory:")
    ingest_dir(conn, tmp_path / "p", "demo", CFG)
    save_matching(conn, compute_matching(load_rows(conn, "demo"), CFG), "demo", CFG)
    run_checks(conn, CFG, "demo")
    create_views(conn, CFG)
    status = {r["work_key"].split(":")[1].split("|")[0][-1]: r["status"] for r in conn.execute("SELECT * FROM position_status")}
    assert status == {"а": "yellow", "б": "green", "в": "green", "г": "green", "д": "red"}


# ---------- name и unit_label в position_status ----------
def strip_markers(text):
    for marker in load_config()["synonyms"]["strip_markers"]:
        text = text.replace(marker, "")
    return text.strip()


@pytest.fixture(scope="module")
def llm_db(synth):
    return build(synth, llm=True)


@pytest.fixture(scope="module")
def rules_db(synth):
    return build(synth, llm=False)


def test_name_and_unit_label_are_filled_for_every_position(llm_db, rules_db):
    rows = llm_db.execute("SELECT * FROM position_status").fetchall()
    assert len(rows) == 47
    for conn in (llm_db, rules_db):
        for r in conn.execute("SELECT * FROM position_status").fetchall():
            assert r["name"] and r["name"].strip() == r["name"], r["work_key"]
            assert r["unit_label"], r["work_key"]
            assert r["unit"] is not None                                         # служебная колонка осталась


def test_name_of_vor_position_is_first_vor_row_raw_name_without_markers(llm_db):
    checked = 0
    for r in llm_db.execute("SELECT * FROM position_status WHERE plan_qty IS NOT NULL").fetchall():
        first = llm_db.execute("SELECT work_name_raw FROM items WHERE doc_type = 'vor' AND work_key = ? "
                               "ORDER BY doc_id, source_row LIMIT 1", (r["work_key"],)).fetchone()[0]
        assert r["name"] == strip_markers(first), r["work_key"]
        checked += 1
    assert checked == 45
    marked = llm_db.execute("SELECT COUNT(*) FROM items WHERE doc_type = 'vor' AND work_name_raw LIKE '%/прим/%'").fetchone()[0]
    assert marked > 0                                                           # пометка в данных есть, а в названии для показа её нет
    assert not llm_db.execute("SELECT 1 FROM position_status WHERE name LIKE '%/прим/%'").fetchall()
    # «Строительный мусор» шесть строк ВОР это одна позиция с названием первой строки
    assert llm_db.execute("SELECT name FROM position_status WHERE work_key = 'work:строительный мусор|t'").fetchone()[0] == "Строительный мусор"


def test_position_only_in_acts_takes_its_name_from_the_first_act_row(llm_db, rules_db):
    rows = llm_db.execute("SELECT * FROM position_status WHERE plan_qty IS NULL ORDER BY name").fetchall()
    assert [r["name"] for r in rows] == ["Монтаж системы видеонаблюдения", "Устройство отмостки вокруг здания"]
    for conn in (llm_db, rules_db):
        for r in conn.execute("SELECT * FROM position_status WHERE plan_qty IS NULL").fetchall():
            first = conn.execute("SELECT work_name_raw FROM items WHERE doc_type = 'act' AND work_key = ? "
                                 "ORDER BY doc_id, source_row LIMIT 1", (r["work_key"],)).fetchone()[0]
            assert r["name"] == first, r["work_key"]                              # название из акта, не из ВОР


def test_unit_label_matches_issues_view_unit_and_old_unit_is_unchanged(llm_db):
    labels = load_config()["rules"]["issues"]["unit_labels"]
    for r in llm_db.execute("SELECT * FROM position_status").fetchall():
        assert r["unit_label"] == labels.get(r["unit"], r["unit"]), r["work_key"]
    pairs = llm_db.execute(
        "SELECT p.unit_label, v.unit FROM position_status p JOIN issues_view v ON v.work_key = p.work_key "
        "WHERE v.issue_type IN ('volume_exceeded', 'price_increase', 'missing_in_vor')").fetchall()
    assert pairs and all(a == b for a, b in pairs)                               # та же единица, что в issues_view.unit
    units = {r["unit"] for r in llm_db.execute("SELECT unit FROM position_status")}
    assert {"m3", "m2", "t"} <= units and not any(any(c in u for c in "мтш") for u in units)     # служебные латинские, как раньше


def test_rerun_keeps_one_row_per_position(synth, tmp_path):
    from src.pipeline import run_pipeline
    db = tmp_path / "again.db"
    counts = []
    for _ in range(2):
        run_pipeline(synth["dir"], db, "rules_only")
        conn = sqlite3.connect(db)
        counts.append(conn.execute("SELECT COUNT(*), COUNT(DISTINCT work_key) FROM position_status").fetchone())
        conn.close()
    assert counts[0] == counts[1] and counts[0][0] == counts[0][1] > 0
