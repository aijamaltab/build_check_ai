"""ИИ-сопоставление строки со списком ВОР (docs/synthetic_spec.md §10, функция «а2»). Реального вызова LLM здесь нет.

RowMatcher.match_row(row, vor_keys) -> {"key": str | None, "confidence": float, "reason": str}: модель выбирает ключ из
ВСЕГО списка ВОР проекта или отвечает «ни один» (key = None). Это второй механизм после PairJudge: PairJudge судит готовые
пары-кандидаты, RowMatcher видит всю таблицу и находит пару там, где кандидатов нет (длинные нормативные названия).
По умолчанию NoopRowMatcher: «не решено» (режим rules_only). Реализацию с Gemini пишет отдельно.

resolve_rows(conn, matcher, cfg, project_id) применяет его к строкам ambiguous и absent. Код проверяет каждый ответ:
ключ есть в ВОР проекта; confidence не ниже llm.min_confidence; единица совпадает; kind совместим; нет конфликта числовых
токенов (llm_veto); ключ ВОР не занят другой группой того же документа (одинаковые названия внутри документа уже слиты в
одну суммируемую группу, поэтому исключений нет). Принятая пара пишется в matches с method = llm, reason сохраняется.
"""
from dataclasses import dataclass
from typing import Protocol

from .names import NameNormalizer
from .store import refresh_kind_dq, set_final_key

class RowMatcher(Protocol):
    available: bool

    def match_row(self, row: dict, vor_keys: list) -> dict: ...


class NoopRowMatcher:
    """Матчер по умолчанию: ничего не решает (режим rules_only). Строки остаются ambiguous или absent."""
    available = False

    def match_row(self, row: dict, vor_keys: list) -> dict:
        return {"key": None, "confidence": 0.0, "reason": "ИИ-матчер не подключён (режим rules_only)"}


@dataclass
class RowResolveStats:
    asked: int = 0
    accepted: int = 0
    none: int = 0                    # модель ответила «ни один» с достаточной уверенностью
    rejected: int = 0                # ответ не принят кодом (по причинам ниже)
    reasons: dict = None
    skipped: int = 0                 # матчер недоступен: строки не тронуты

    def __post_init__(self):
        self.reasons = {}


def _valid(answer) -> bool:
    return (isinstance(answer, dict) and (answer.get("key") is None or isinstance(answer.get("key"), str))
            and isinstance(answer.get("confidence"), (int, float)) and not isinstance(answer.get("confidence"), bool)
            and 0 <= answer["confidence"] <= 1 and isinstance(answer.get("reason"), str))


def _first_row(conn, group_id: int):
    return conn.execute(
        "SELECT i.work_name_raw, i.source_file, i.source_sheet, i.source_row, i.quantity, i.unit_price FROM staging_match_rows r "
        "JOIN items i ON i.item_id = r.item_id WHERE r.group_id = ? ORDER BY i.source_row LIMIT 1", (group_id,)).fetchone()


def vor_key_list(conn, project_id: str) -> list:
    """Все ключи ВОР проекта: то, из чего модель выбирает."""
    out = []
    for g in conn.execute("SELECT * FROM staging_match_groups WHERE project_id = ? AND doc_type = 'vor' ORDER BY group_id", (project_id,)):
        first = _first_row(conn, g["group_id"])
        est = conn.execute("SELECT i.unit_price FROM staging_match_groups e JOIN items i ON i.item_id = e.first_item_id "
                           "WHERE e.matched_group_id = ? AND e.doc_type = 'estimate' LIMIT 1", (g["group_id"],)).fetchone()
        # plan_qty и estimate_price это контекст для модели (слабые сигналы); решает не формула, а ИИ, проверяет код
        out.append({"key": g["final_work_key"], "name_raw": first["work_name_raw"], "name": g["name"], "unit": g["unit_norm"],
                    "kind": g["kind"], "file": first["source_file"], "sheet": first["source_sheet"], "row": first["source_row"],
                    "plan_qty": g["qty_sum"], "estimate_price": est["unit_price"] if est else None})
    return out


def resolve_rows(conn, matcher: RowMatcher, cfg: dict, project_id: str) -> RowResolveStats:
    init = conn.execute("SELECT * FROM staging_match_run WHERE project_id = ?", (project_id,)).fetchone()
    stats = RowResolveStats()
    todo = conn.execute("SELECT * FROM staging_match_groups WHERE project_id = ? AND doc_type != 'vor' AND status IN "
                        "('ambiguous', 'absent') ORDER BY doc_id, first_item_id", (project_id,)).fetchall()
    if not getattr(matcher, "available", True):
        stats.skipped = len(todo)
        return stats
    norm = NameNormalizer(cfg["synonyms"], cfg["rules"], bool(init["use_synonyms"]), init["missing_side"])
    min_conf = cfg["rules"]["llm"]["min_confidence"]
    vor_keys = vor_key_list(conn, project_id)
    vor_by_key = {r["final_work_key"]: r for r in conn.execute(
        "SELECT * FROM staging_match_groups WHERE project_id = ? AND doc_type = 'vor'", (project_id,))}

    answers = []
    for g in todo:                                    # сначала все вопросы к модели, затем применение по убыванию уверенности
        first = _first_row(conn, g["group_id"])
        row = {"name_raw": first["work_name_raw"], "name": g["name"], "unit": g["unit_norm"], "kind": g["signal"],
               "file": first["source_file"], "sheet": first["source_sheet"], "row": first["source_row"],
               "quantity": g["qty_sum"], "unit_price": first["unit_price"], "doc_type": g["doc_type"], "state": g["status"]}
        answer = matcher.match_row(row, vor_keys)
        stats.asked += 1
        if not _valid(answer):
            answer = {"key": None, "confidence": 0.0, "reason": "ответ не по схеме", "_invalid": True}
        answers.append((g, answer))
    answers.sort(key=lambda x: -x[1]["confidence"])   # sort стабилен: при равной уверенности порядок документа

    def decide(g, answer, outcome):
        conn.execute("INSERT INTO staging_llm_row_decisions (project_id, group_id, chosen_key, confidence, reason, outcome) "
                     "VALUES (?,?,?,?,?,?)", (project_id, g["group_id"], answer["key"], answer["confidence"], answer["reason"], outcome))
        if outcome.startswith("rejected"):
            stats.rejected += 1
            stats.reasons[outcome] = stats.reasons.get(outcome, 0) + 1

    for g, answer in answers:
        key = answer["key"]
        if answer.get("_invalid"):
            decide(g, answer, "rejected: invalid")
            continue
        if key is None:
            decide(g, answer, "none")
            if answer["confidence"] >= min_conf:      # модель уверенно сказала «ни один»: пары в ВОР нет
                stats.none += 1
                conn.execute("UPDATE staging_match_groups SET status = 'absent' WHERE group_id = ?", (g["group_id"],))
                conn.execute("UPDATE staging_match_rows SET state = 'absent' WHERE group_id = ?", (g["group_id"],))
                conn.execute("UPDATE staging_match_candidates SET status = 'rejected', judge_reason = ?, judge_confidence = ? "
                             "WHERE group_id = ? AND status = 'open'", (answer["reason"], answer["confidence"], g["group_id"]))
            continue
        vor = vor_by_key.get(key)
        if vor is None:
            decide(g, answer, "rejected: key not in VOR")
        elif answer["confidence"] < min_conf:
            decide(g, answer, "rejected: low confidence")
        elif g["unit_norm"] is None or g["unit_norm"] != vor["unit_norm"]:
            decide(g, answer, "rejected: unit")
        elif g["signal"] is not None and g["signal"] != vor["kind"]:
            decide(g, answer, "rejected: kind")
        elif norm.is_vetoed(norm.conflicts(norm.prepare(g["name"]), norm.prepare(vor["name"]))):
            decide(g, answer, "rejected: numeric tokens")
        elif conn.execute("SELECT 1 FROM staging_match_groups WHERE doc_id = ? AND matched_group_id = ?",
                          (g["doc_id"], vor["group_id"])).fetchone():
            decide(g, answer, "rejected: key taken")
        else:
            decide(g, answer, "accepted")
            stats.accepted += 1
            for r in conn.execute("SELECT item_id FROM staging_match_rows WHERE group_id = ?", (g["group_id"],)).fetchall():
                mid = conn.execute("INSERT INTO matches (work_key, item_id, matched_to_item_id, score, method) VALUES (?,?,?,?,'llm')",
                                   (key, r["item_id"], vor["first_item_id"], None)).lastrowid
                conn.execute("INSERT INTO staging_matches_ext (match_id, group_id, state, stage, kind, reason, confidence) "
                             "VALUES (?,?,'matched','llm_row',?,?,?)", (mid, g["group_id"], vor["kind"], answer["reason"], answer["confidence"]))
            conn.execute("UPDATE staging_match_groups SET status = 'matched', matched_group_id = ?, kind = ? WHERE group_id = ?",
                         (vor["group_id"], vor["kind"], g["group_id"]))
            conn.execute("UPDATE staging_match_rows SET state = 'matched' WHERE group_id = ?", (g["group_id"],))
            set_final_key(conn, g["group_id"], key)
            conn.execute("UPDATE staging_match_candidates SET status = 'superseded' WHERE group_id = ? AND status = 'open'",
                         (g["group_id"],))
    refresh_kind_dq(conn, project_id, cfg)
    conn.commit()
    return stats
