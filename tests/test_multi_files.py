"""Несколько файлов одного типа: pipeline читает несколько ВОР, актов и смет; пара позиции акта ищется во всех ВОР проекта."""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.pipeline import run_pipeline
from tests.cache_guard import REAL_CACHE

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_matching as vm  # noqa: E402

DEMO = ROOT / "data" / "synthetic"


@pytest.fixture(scope="module")
def truth():
    return vm.load_truth()


def pipeline(tmp_path, names, truth, tag):
    folder = tmp_path / tag
    folder.mkdir()
    for n in names:
        shutil.copy(DEMO / n, folder / n)
    db = tmp_path / f"{tag}.db"
    summary = run_pipeline(folder, db, "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth), cfg=None)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return summary, conn


def missing_rows(conn):
    return {(r["source_file"], r["source_row"]) for r in conn.execute("SELECT * FROM issues_view WHERE issue_type = 'missing_in_vor'")}


def test_act_position_finds_its_pair_in_the_second_of_two_vor_files(tmp_path, truth):
    # act_3 содержит работы из обоих ВОР (электрика и отопление только в vor_2) и позицию, которой нет ни в одной ведомости
    summary, conn = pipeline(tmp_path, ["vor_1.xlsx", "vor_2.xlsx", "act_3.xlsx"], truth, "both")
    no_vor = {key for key, item in truth.items() if item in vm.NO_VOR_ITEMS}
    assert summary["files"] == 3 and summary["documents_with_errors"] == []
    assert missing_rows(conn) <= no_vor and missing_rows(conn)                                    # «нет в ВОР» только у позиции, которой нет нигде
    sources = {r[0] for r in conn.execute(
        "SELECT DISTINCT v.source_file FROM matches m JOIN items a ON a.item_id = m.item_id JOIN items v ON v.item_id = m.matched_to_item_id "
        "WHERE a.source_file = 'act_3.xlsx'")}
    assert sources == {"vor_1.xlsx", "vor_2.xlsx"}                                                # пары есть в обоих ВОР, файл-источник сохранён
    files = {r[0] for r in conn.execute("SELECT DISTINCT source_file FROM items WHERE doc_type = 'vor'")}
    assert files == {"vor_1.xlsx", "vor_2.xlsx"}


def test_control_without_the_second_vor_the_same_act_rows_have_no_pair(tmp_path, truth):
    _, conn = pipeline(tmp_path, ["vor_1.xlsx", "act_3.xlsx"], truth, "one")
    no_vor = {key for key, item in truth.items() if item in vm.NO_VOR_ITEMS}
    assert len(missing_rows(conn) - no_vor) >= 5                                                   # без vor_2 те же строки акта «нет в ВОР»


def test_several_vor_acts_and_estimates_are_read_together(tmp_path, truth):
    names = ["vor_1.xlsx", "vor_2.xlsx", "estimate.xlsx", "act_1.xlsx", "act_2.xlsx", "act_3.xlsx"]
    summary, conn = pipeline(tmp_path, names, truth, "many")
    assert summary["files"] == 6 and summary["documents_with_errors"] == []
    for doc_type, expected in (("vor", {"vor_1.xlsx", "vor_2.xlsx"}), ("act", {"act_1.xlsx", "act_2.xlsx", "act_3.xlsx"})):
        assert {r[0] for r in conn.execute("SELECT DISTINCT source_file FROM items WHERE doc_type = ?", (doc_type,))} == expected
    # у расхождений остаётся «файл · лист · строка» исходного файла
    for issue in conn.execute("SELECT source_file, source_sheet, source_row FROM issues_view WHERE issue_type != 'late_act'"):
        assert issue["source_file"] in names and issue["source_sheet"] and issue["source_row"] > 0


def test_two_estimate_files_do_not_break_price_check(tmp_path, truth):
    folder = tmp_path / "est"
    folder.mkdir()
    for n in ("vor_1.xlsx", "vor_2.xlsx", "estimate.xlsx", "act_1.xlsx", "act_2.xlsx"):
        shutil.copy(DEMO / n, folder / n)
    shutil.copy(DEMO / "estimate.xlsx", folder / "estimate_copy.xlsx")                            # вторая смета с теми же ценами
    db = tmp_path / "est.db"
    run_pipeline(folder, db, "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth))
    base = tmp_path / "est1.db"
    one = tmp_path / "est1"
    one.mkdir()
    for n in ("vor_1.xlsx", "vor_2.xlsx", "estimate.xlsx", "act_1.xlsx", "act_2.xlsx"):
        shutil.copy(DEMO / n, one / n)
    run_pipeline(one, base, "llm", judge=vm.TruthJudge(truth), row_matcher=vm.TruthRowMatcher(truth))
    prices = lambda p: sorted(  # noqa: E731
        (r[0], r[1]) for r in sqlite3.connect(p).execute("SELECT work_key, actual FROM issues WHERE issue_type = 'price_increase'"))
    assert prices(db) == prices(base) and prices(db)                                               # цена по ключу средневзвешенная: дубль сметы её не меняет


@pytest.fixture()
def llm_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def upload_app():
    from ui.screens import upload
    upload.render()


def test_upload_page_accepts_several_files_of_each_type(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    assert not at.exception
    multi = {u.key: u.proto.multiple_files for u in at.file_uploader}
    assert multi == {"upload_vor": True, "upload_acts": True, "upload_estimate": True, "upload_contract": False}   # договор один
    for f in ("vor_1.xlsx", "vor_2.xlsx"):
        at.file_uploader(key="upload_vor").upload(f, (DEMO / f).read_bytes())
    at.file_uploader(key="upload_acts").upload("act_3.xlsx", (DEMO / "act_3.xlsx").read_bytes())
    at.button(key="upload_run").click().run()
    assert not at.exception and not at.error
    items = at.session_state["run_result"]["results"]["items"]
    assert set(items[items["doc_type"] == "vor"]["source_file"]) == {"vor_1.xlsx", "vor_2.xlsx"}
    assert at.session_state["run_result"]["summary"]["files"] == 3
