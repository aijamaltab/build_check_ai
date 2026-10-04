"""GeminiPairJudge: PairJudge на Gemini (docs/synthetic_spec.md §10, функция «а»).

Модель говорит «та же работа или нет», но решает код: числовые токены, слова взаимоисключающих групп, единица и вид работ
не обходятся ответом модели; уверенность ниже llm.min_confidence это «нет решения». Нет ответа возвращается как None:
resolve_candidates оставляет такую строку ambiguous (а не absent, иначе сбой ИИ превратился бы в ложное missing_in_vor).
"""
from src.matching.names import NameNormalizer

from .cache import normalize_text
from .client import LlmClient
from .prompts import GRADE_REFERENCE, PAIR_PROMPT, PAIR_PROMPT_VERSION, PAIR_SCHEMA, UNKNOWN_KIND_RULE

KNOWN_KINDS = ("work", "material")


def valid_pair_answer(answer) -> bool:
    return (isinstance(answer, dict) and isinstance(answer.get("same_work"), bool)
            and isinstance(answer.get("confidence"), (int, float)) and not isinstance(answer.get("confidence"), bool)
            and 0 <= answer["confidence"] <= 1 and isinstance(answer.get("reason"), str))


class GeminiPairJudge:
    def __init__(self, client: LlmClient, cfg: dict):
        self.client = client
        llm = cfg["rules"]["llm"]
        self.min_confidence = llm["min_confidence"]
        self.hard = set(llm.get("judge_hard_conflicts", ["patterns"]))
        self.norm = NameNormalizer(cfg["synonyms"], cfg["rules"], True)

    @property
    def available(self) -> bool:
        return self.client.available

    @property
    def stats(self):
        return self.client.stats

    @property
    def stop_reason(self):
        return self.client.stop_reason

    @property
    def warnings(self):
        return self.client.warnings

    def _hard_conflict(self, a: dict, b: dict) -> str | None:
        """Причина, по которой пара точно не та же работа (проверка кодом, не моделью)."""
        if a.get("unit") != b.get("unit"):
            return f"единицы различаются: {a.get('unit')} и {b.get('unit')}"
        if a.get("kind") in KNOWN_KINDS and b.get("kind") in KNOWN_KINDS and a["kind"] != b["kind"]:
            return f"вид различается: {a['kind']} и {b['kind']}"
        conflicts = self.norm.conflicts(self.norm.prepare(a["name"]), self.norm.prepare(b["name"]))
        hard = [text for kind, text in conflicts if kind in self.hard]
        return "; ".join(hard) if hard else None

    def judge_pair(self, a: dict, b: dict, context: dict | None = None) -> dict | None:
        side = lambda x: (x.get("name_raw") or x.get("name") or "", x.get("unit") or "-", x.get("kind") or "-")  # noqa: E731
        (an, au, ak), (bn, bu, bk) = side(a), side(b)
        payload = {"a": [normalize_text(an), au, ak], "b": [normalize_text(bn), bu, bk]}
        shown = lambda kind: kind if kind in KNOWN_KINDS else "неизвестен"  # noqa: E731
        prompt = PAIR_PROMPT.format(a_name=an, a_unit=au, a_kind=shown(ak), b_name=bn, b_unit=bu, b_kind=shown(bk),
                                    unknown_kind_rule=UNKNOWN_KIND_RULE, grade_reference=GRADE_REFERENCE)
        answer = self.client.ask("pair", PAIR_PROMPT_VERSION, payload, prompt, PAIR_SCHEMA, valid_pair_answer)
        if answer is None:
            return None
        if answer["confidence"] < self.min_confidence:
            self.client.stats.low_confidence += 1
            return None
        if answer["same_work"]:
            reason = self._hard_conflict(a, b)
            if reason:
                self.client.stats.rejected_by_check += 1
                return {"same_work": False, "confidence": answer["confidence"],
                        "reason": f"отклонено проверкой: {reason} (ответ модели: {answer['reason']})"}
        return {"same_work": answer["same_work"], "confidence": float(answer["confidence"]), "reason": answer["reason"]}
