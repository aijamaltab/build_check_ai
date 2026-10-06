"""LLM-шаг через интерфейс (docs/synthetic_spec.md §10, функция «а»). Реального вызова LLM здесь нет.

PairJudge.judge_pair(a, b, context) -> {"same_work": bool, "confidence": float, "reason": str}. Реальную реализацию
(Gemini, кэш, схема JSON) пишет отдельно. По умолчанию NoopJudge: «не решено», режим rules_only.
resolve_candidates(conn, judge, cfg, project_id) разбирает таблицу кандидатов: принятые пары пишутся в matches
с method = llm, reason и confidence сохраняются в staging_matches_ext. Код остаётся главным: ответ принимается
только если confidence не ниже llm.min_confidence и у пары нет конфликта числовых токенов (llm_veto).
"""
from dataclasses import dataclass
from typing import Protocol

from .names import NameNormalizer
from .store import refresh_kind_dq, set_final_key, work_key


class PairJudge(Protocol):
    available: bool

    def judge_pair(self, a: dict, b: dict, context: dict) -> dict: ...


class NoopJudge:
    """Судья по умолчанию: ничего не решает (режим rules_only). Кандидаты остаются «не сопоставлены»."""
    available = False

    def judge_pair(self, a: dict, b: dict, context: dict) -> dict:
        return {"same_work": False, "confidence": 0.0, "reason": "ИИ-судья не подключён (режим rules_only)"}


@dataclass
class ResolveStats:
    asked: int = 0
    accepted: int = 0
    rejected: int = 0
    vetoed: int = 0
    invalid: int = 0
    superseded: int = 0
    skipped: int = 0                # судья недоступен: кандидаты не тронуты


def demote_judged_ambiguous(conn, project_id: str) -> None:
    """Судья отклонил все кандидаты строки (и открытых не осталось): она absent, то есть кандидат на missing_in_vor.
    Строки с невалидными ответами судьи остаются ambiguous (решения не было)."""
    groups = conn.execute("SELECT group_id FROM staging_match_groups WHERE project_id = ? AND status = 'ambiguous'",
                          (project_id,)).fetchall()
    for g in groups:
        statuses = {r[0] for r in conn.execute("SELECT status FROM staging_match_candidates WHERE group_id = ?", (g["group_id"],))}
        if statuses and not statuses & {"open", "invalid", "accepted"} and statuses & {"rejected", "vetoed"}:
            conn.execute("UPDATE staging_match_groups SET status = 'absent' WHERE group_id = ?", (g["group_id"],))
            conn.execute("UPDATE staging_match_rows SET state = 'absent' WHERE group_id = ?", (g["group_id"],))


def _valid(answer) -> bool:
    return (isinstance(answer, dict) and isinstance(answer.get("same_work"), bool)
            and isinstance(answer.get("confidence"), (int, float)) and not isinstance(answer.get("confidence"), bool)
            and 0 <= answer["confidence"] <= 1 and isinstance(answer.get("reason"), str))


def _describe(conn, group_id: int) -> dict:
    g = conn.execute("SELECT * FROM staging_match_groups WHERE group_id = ?", (group_id,)).fetchone()
    first = conn.execute(
        "SELECT i.work_name_raw, i.source_file, i.source_sheet, i.source_row FROM staging_match_rows r "
        "JOIN items i ON i.item_id = r.item_id WHERE r.group_id = ? ORDER BY i.source_row LIMIT 1", (group_id,)).fetchone()
    # kind строки документа вне ВОР: g["kind"] там значение по умолчанию (work), настоящий признак лежит в signal (None = неизвестен).
    # У строк ВОР вид известен всегда (g["kind"]).
    kind = g["kind"] if g["doc_type"] == "vor" else g["signal"]
    return {"name_raw": first["work_name_raw"], "name": g["name"], "unit": g["unit_norm"], "kind": kind,
            "file": first["source_file"], "sheet": first["source_sheet"], "row": first["source_row"]}


def resolve_candidates(conn, judge: PairJudge, cfg: dict, project_id: str) -> ResolveStats:
    stats = ResolveStats()
    open_rows = conn.execute(
        "SELECT * FROM staging_match_candidates WHERE project_id = ? AND status = 'open' ORDER BY score DESC, candidate_id",
        (project_id,)).fetchall()
    if not getattr(judge, "available", True):
        stats.skipped = len(open_rows)
        return stats
    run = conn.execute("SELECT * FROM staging_match_run WHERE project_id = ?", (project_id,)).fetchone()
    norm = NameNormalizer(cfg["synonyms"], cfg["rules"], bool(run["use_synonyms"]), run["missing_side"])
    min_conf = cfg["rules"]["llm"]["min_confidence"]
    notify = getattr(judge, "progress", None)         # необязательный отчёт о ходе (страница живого ИИ): (стадия, сделано, всего)
    if notify:
        notify("pairs", 0, len(open_rows))
    for done, cand in enumerate(open_rows, 1):
        if notify and done > 1:
            notify("pairs", done - 1, len(open_rows))
        doc = conn.execute("SELECT * FROM staging_match_groups WHERE group_id = ?", (cand["group_id"],)).fetchone()
        vor = conn.execute("SELECT * FROM staging_match_groups WHERE group_id = ?", (cand["candidate_group_id"],)).fetchone()
        taken = conn.execute("SELECT 1 FROM staging_match_groups WHERE doc_id = ? AND matched_group_id = ?",
                             (doc["doc_id"], vor["group_id"])).fetchone()
        if doc["status"] != "ambiguous" or taken:
            conn.execute("UPDATE staging_match_candidates SET status = 'superseded' WHERE candidate_id = ?", (cand["candidate_id"],))
            stats.superseded += 1
            continue
        a, b = _describe(conn, doc["group_id"]), _describe(conn, vor["group_id"])
        answer = judge.judge_pair(a, b, {"score": cand["score"], "reason_for_review": cand["reason_for_review"],
                                         "doc_type": doc["doc_type"]})
        stats.asked += 1
        status = "rejected"
        if not _valid(answer):                       # None: ИИ не ответил, строка остаётся ambiguous
            reason = "ИИ не дал решения" if answer is None else "ответ не по схеме"
            status, answer = "invalid", {"same_work": False, "confidence": 0.0, "reason": reason}
            stats.invalid += 1
        elif answer["same_work"] and answer["confidence"] >= min_conf:
            conflicts = norm.conflicts(norm.prepare(doc["name"]), norm.prepare(vor["name"]))
            if norm.is_vetoed(conflicts):
                status = "vetoed"
                stats.vetoed += 1
            else:
                status = "accepted"
        if status == "rejected":
            stats.rejected += 1
        conn.execute("UPDATE staging_match_candidates SET status = ?, judge_reason = ?, judge_confidence = ? "
                     "WHERE candidate_id = ?", (status, answer["reason"], answer["confidence"], cand["candidate_id"]))
        if status != "accepted":
            continue
        key = work_key(cfg, vor["kind"], vor["name"], vor["unit_norm"])
        for row in conn.execute("SELECT item_id FROM staging_match_rows WHERE group_id = ?", (doc["group_id"],)).fetchall():
            mid = conn.execute("INSERT INTO matches (work_key, item_id, matched_to_item_id, score, method) VALUES (?,?,?,?,'llm')",
                               (key, row["item_id"], vor["first_item_id"], cand["score"])).lastrowid
            conn.execute("INSERT INTO staging_matches_ext (match_id, group_id, state, stage, kind, reason, confidence) "
                         "VALUES (?,?,'matched','llm',?,?,?)", (mid, doc["group_id"], vor["kind"], answer["reason"], answer["confidence"]))
        conn.execute("UPDATE staging_match_groups SET status = 'matched', matched_group_id = ?, kind = ? WHERE group_id = ?",
                     (vor["group_id"], vor["kind"], doc["group_id"]))
        conn.execute("UPDATE staging_match_rows SET state = 'matched' WHERE group_id = ?", (doc["group_id"],))
        set_final_key(conn, doc["group_id"], key)
        conn.execute("UPDATE staging_match_candidates SET status = 'superseded' WHERE project_id = ? AND status = 'open' "
                     "AND (group_id = ? OR (candidate_group_id = ? AND group_id IN "
                     "(SELECT group_id FROM staging_match_groups WHERE doc_id = ?)))",
                     (project_id, doc["group_id"], vor["group_id"], doc["doc_id"]))
        stats.accepted += 1
    demote_judged_ambiguous(conn, project_id)
    refresh_kind_dq(conn, project_id, cfg)
    conn.commit()
    if notify:
        notify("pairs", len(open_rows), len(open_rows))
    return stats
