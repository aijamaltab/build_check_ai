"""Таблица кандидатов для LLM, интерфейс PairJudge, NoopJudge и resolve_candidates (реального LLM нет, судья фейковый)."""
import pytest

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.matching import NoopJudge, compute_matching, load_rows, resolve_candidates, save_matching
from tests.test_generate_synthetic import gen

CFG = load_config()
M = CFG["rules"]["matching"]


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    generated = gen.generate(out_dir=out, meta_dir=out)
    return out, {(r["file"], r["row"]): r["item_no"] for r in generated.log}


@pytest.fixture()
def db(synth):
    """Свежая база с данными и сохранённым результатом matching (rules_only, порог из конфига)."""
    conn = get_connection(":memory:")
    ingest_dir(conn, synth[0], "demo", CFG)
    result = compute_matching(load_rows(conn, "demo"), CFG)
    save_matching(conn, result, "demo", CFG)
    return conn, result


def q(conn, sql, *args):
    return [tuple(r) for r in conn.execute(sql, args)]


class TruthJudge:
    """Фейковый судья: говорит same_work = true, если эталон генератора считает строки одной работой."""
    available = True

    def __init__(self, truth, confidence=0.95):
        self.truth, self.confidence, self.calls = truth, confidence, []

    def judge_pair(self, a, b, context):
        self.calls.append((a, b, context))
        same = self.truth[(a["file"], a["row"])] == self.truth.get((b["file"], b["row"]), "?")
        return {"same_work": same, "confidence": self.confidence, "reason": "фейковый судья по эталону"}


# ---------- запись в БД и кандидаты ----------
def test_matches_follow_contract_and_final_key(db):
    conn, result = db
    assert q(conn, "SELECT DISTINCT method FROM matches ORDER BY method") == [("exact",), ("fuzzy",)]
    # у сопоставленной строки ключ равен ключу строки ВОР, к которой она привязана
    bad = q(conn, "SELECT COUNT(*) FROM matches m JOIN items a ON a.item_id = m.item_id JOIN items v ON v.item_id = m.matched_to_item_id "
                  "WHERE a.work_key != v.work_key OR m.work_key != v.work_key")
    assert bad == [(0,)]
    n_rows = sum(len(p.doc.rows) for p in result.pairs)
    assert q(conn, "SELECT COUNT(*) FROM matches") == [(n_rows,)]
    stages = {s for (s,) in q(conn, "SELECT DISTINCT stage FROM staging_matches_ext")}
    assert stages == {"exact", "synonyms", "fuzzy"}


def test_vor_rows_of_one_key_share_the_final_key(db):
    conn, _ = db
    keys = q(conn, "SELECT DISTINCT work_key FROM items WHERE source_file = 'vor_2.xlsx' AND work_name_raw LIKE 'Строительный мусор%'")
    assert keys == [("work:строительный мусор|t",)]


def test_candidates_table_contract(db):
    conn, result = db
    rows = q(conn, "SELECT item_id, candidate_item_id, score, reason_for_review, status FROM staging_match_candidates")
    assert rows and len(rows) == len(result.candidates)
    assert all(status == "open" and reason for *_, reason, status in rows)
    lower, upper = M["llm_lower_bound"], M["fuzzy_threshold"]
    for _, _, score, reason, _ in rows:
        assert score >= lower and ("score" in reason or "против" in reason)       # зона либо конфликт слов или скобок
    per_row = q(conn, "SELECT MAX(n) FROM (SELECT COUNT(*) n FROM staging_match_candidates GROUP BY group_id)")[0][0]
    assert per_row <= M["llm_candidates_per_row"]
    # кандидаты только у несопоставленных групп
    assert q(conn, "SELECT COUNT(*) FROM staging_match_candidates c JOIN staging_match_groups g ON g.group_id = c.group_id "
                   "WHERE g.status != 'unmatched'") == [(0,)]


def test_kind_unknown_dq_is_diagnostic_not_issue(db):
    conn, _ = db
    name = M["kind_unknown_dq_check"]
    rows = q(conn, "SELECT passed FROM dq_checks WHERE check_name = ?", name)
    assert rows and all(p == 0 for (p,) in rows)
    assert q(conn, "SELECT COUNT(*) FROM issues") == [(0,)]


def test_save_is_idempotent(synth):
    conn = get_connection(":memory:")
    ingest_dir(conn, synth[0], "demo", CFG)
    rows = load_rows(conn, "demo")
    for _ in range(2):
        save_matching(conn, compute_matching(rows, CFG), "demo", CFG)
    assert q(conn, "SELECT COUNT(*) FROM staging_match_run") == [(1,)]
    assert q(conn, "SELECT COUNT(*) FROM matches") == q(conn, "SELECT COUNT(*) FROM staging_matches_ext")
    assert q(conn, "SELECT COUNT(*) FROM dq_checks WHERE check_name = ?", M["kind_unknown_dq_check"]) == [(6,)]


# ---------- судья ----------
def test_noop_judge_changes_nothing(db):
    conn, _ = db
    before = (q(conn, "SELECT COUNT(*) FROM matches"), q(conn, "SELECT COUNT(*) FROM staging_match_candidates WHERE status = 'open'"))
    stats = resolve_candidates(conn, NoopJudge(), CFG, "demo")
    assert stats.skipped == before[1][0][0] and stats.asked == stats.accepted == 0
    assert q(conn, "SELECT COUNT(*) FROM matches") == before[0]
    assert NoopJudge().judge_pair({}, {}, {})["same_work"] is False


def test_fake_judge_accepts_a_given_pair_and_saves_reason(db, synth):
    conn, result = db
    cand = next(c for c in result.candidates if len({r.source_row for r in c.doc.rows}) == 1 and
                synth[1][(c.doc.first.file, c.doc.first.source_row)] == synth[1][(c.vor.first.file, c.vor.first.source_row)])
    judge = TruthJudge(synth[1])
    stats = resolve_candidates(conn, judge, CFG, "demo")
    assert stats.asked == len(judge.calls) > 0 and stats.accepted > 0
    item_id = cand.doc.first.item_id
    m = q(conn, "SELECT m.method, m.work_key, v.work_key, e.stage, e.reason, e.confidence FROM matches m "
                "JOIN items v ON v.item_id = m.matched_to_item_id JOIN staging_matches_ext e ON e.match_id = m.match_id "
                "WHERE m.item_id = ?", item_id)
    assert m and m[0][0] == "llm" and m[0][1] == m[0][2] and m[0][3] == "llm"
    assert m[0][4] == "фейковый судья по эталону" and m[0][5] == 0.95
    assert q(conn, "SELECT work_key FROM items WHERE item_id = ?", item_id) == [(m[0][1],)]       # ключ строки ВОР
    assert q(conn, "SELECT status FROM staging_match_candidates WHERE item_id = ? AND candidate_item_id = ?",
             item_id, cand.vor.first.item_id) == [("accepted",)]
    # a, b и context содержат то, что нужно судье
    a, b, ctx = judge.calls[0]
    assert {"name_raw", "name", "unit", "kind", "file", "sheet", "row"} <= set(a) and {"score", "reason_for_review"} <= set(ctx)


def test_truth_judge_resolves_without_false_merges_and_each_row_once(db, synth):
    conn, result = db
    before = q(conn, "SELECT COUNT(*) FROM staging_match_groups WHERE status = 'unmatched'")[0][0]
    resolve_candidates(conn, TruthJudge(synth[1]), CFG, "demo")
    after = q(conn, "SELECT COUNT(*) FROM staging_match_groups WHERE status = 'unmatched'")[0][0]
    assert after < before
    llm = q(conn, "SELECT a.source_file, a.source_row, v.source_file, v.source_row FROM matches m JOIN items a ON a.item_id = m.item_id "
                  "JOIN items v ON v.item_id = m.matched_to_item_id WHERE m.method = 'llm'")
    assert llm and all(synth[1][(f, r)] == synth[1][(vf, vr)] for f, r, vf, vr in llm)
    assert q(conn, "SELECT COUNT(*) FROM (SELECT item_id FROM matches GROUP BY item_id HAVING COUNT(*) > 1)") == [(0,)]
    # одно ВОР-строка не принята двумя группами одного документа
    assert q(conn, "SELECT COUNT(*) FROM (SELECT doc_id, matched_group_id FROM staging_match_groups "
                   "WHERE matched_group_id IS NOT NULL GROUP BY doc_id, matched_group_id HAVING COUNT(*) > 1)") == [(0,)]


def test_low_confidence_and_invalid_answers_are_not_accepted(db, synth):
    conn, _ = db
    stats = resolve_candidates(conn, TruthJudge(synth[1], confidence=0.1), CFG, "demo")        # ниже llm.min_confidence
    assert stats.accepted == 0 and stats.rejected == stats.asked > 0

    class Broken:
        available = True

        def judge_pair(self, a, b, context):
            return {"same_work": "да", "confidence": 5, "reason": None}

    conn2 = get_connection(":memory:")
    ingest_dir(conn2, synth[0], "demo", CFG)
    save_matching(conn2, compute_matching(load_rows(conn2, "demo"), CFG), "demo", CFG)
    stats = resolve_candidates(conn2, Broken(), CFG, "demo")
    assert stats.invalid == stats.asked > 0 and stats.accepted == 0
    assert q(conn2, "SELECT COUNT(*) FROM matches WHERE method = 'llm'") == [(0,)]


def test_judge_cannot_override_numeric_token_conflict(synth):
    """Конфликт числовых токенов (d12 и d8, если оба токена есть) пару в кандидаты не пускает вовсе,
    а при принудительной записи кандидата судья всё равно получит veto."""
    from tests.test_matching import row
    rows = [row(1, "арматура а500 d12", unit="t"), row(2, "арматура а500 d8", unit="t", doc_id=2, doc_type="act")]
    res = compute_matching(rows, CFG, threshold=95)
    assert res.pairs == [] and res.candidates == [] and len(res.blocked) == 1


def test_resolve_vetoes_numeric_conflict_even_if_judge_says_yes(db):
    """Прямой тест veto: кандидат d8 -> d12 вставлен вручную, судья отвечает «да» с уверенностью 1."""
    conn, _ = db
    d8 = conn.execute("SELECT group_id, first_item_id FROM staging_match_groups WHERE name = 'арматура гладкая d8' "
                      "AND status = 'unmatched' LIMIT 1").fetchone()
    d12 = conn.execute("SELECT group_id, first_item_id FROM staging_match_groups WHERE doc_type = 'vor' AND name = 'арматура а500 d12'").fetchone()
    conn.execute("DELETE FROM staging_match_candidates")
    # строка ВОР d12 в этом акте занята своей парой; для теста освобождаем её, иначе кандидат будет superseded
    conn.execute("UPDATE staging_match_groups SET matched_group_id = NULL WHERE matched_group_id = ?", (d12["group_id"],))
    conn.execute("INSERT INTO staging_match_candidates (project_id, item_id, candidate_item_id, group_id, candidate_group_id, score, "
                 "reason_for_review) VALUES ('demo', ?, ?, ?, ?, 70, 'тест')", (d8["first_item_id"], d12["first_item_id"],
                                                                                d8["group_id"], d12["group_id"]))

    class AlwaysYes:
        available = True

        def judge_pair(self, a, b, context):
            return {"same_work": True, "confidence": 1.0, "reason": "да"}

    stats = resolve_candidates(conn, AlwaysYes(), CFG, "demo")
    assert (stats.asked, stats.vetoed, stats.accepted) == (1, 1, 0)
    assert q(conn, "SELECT status FROM staging_match_candidates") == [("vetoed",)]
    assert q(conn, "SELECT COUNT(*) FROM matches WHERE method = 'llm'") == [(0,)]
