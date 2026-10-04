"""Сопоставление групп документов со строками ВОР (docs/synthetic_spec.md §6, «Строка без пары»).

Для каждого документа (смета, каждый акт) отдельно, один к одному, жадно по убыванию (token_set_ratio, token_sort_ratio):
  проход 1: группы с признаком материала только с материалами ВОР; проход 2: остальные со всеми свободными группами ВОР.
  Этапы: exact (одинаковый ключ) -> synonyms (одинаковое название после словаря) -> fuzzy (score не ниже порога
  и без конфликта must_match_tokens). Единица измерения должна совпадать.
  Пара со score от llm_lower_bound до порога, пара с конфликтом слов или скобок и пара-«подмножество»
  (token_set_ratio = 100 при token_sort_ratio ниже subset_review_below) идут в кандидаты для LLM, а не сливаются. Пара с конфликтом числовых токенов (d12 против d8) не сливается и в кандидаты не идёт.
Реальных вызовов LLM здесь нет: кандидатов разбирает src/matching/judge.py.
"""
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .groups import Group, build_groups
from .names import NameNormalizer


@dataclass
class Pair:
    doc: Group
    vor: Group
    score: float
    score2: float
    stage: str                    # exact | synonyms | fuzzy | llm
    reason: str | None = None
    confidence: float | None = None

    @property
    def method(self) -> str:
        return "llm" if self.stage == "llm" else ("fuzzy" if self.stage == "fuzzy" else "exact")


@dataclass
class Candidate:
    doc: Group
    vor: Group
    score: float
    reason: str                   # reason_for_review


@dataclass
class MatchResult:
    use_synonyms: bool
    threshold: float
    missing_side: str
    groups: list
    pairs: list = field(default_factory=list)
    candidates: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)       # группы документов без пары (в том числе имеющие кандидатов)
    blocked: list = field(default_factory=list)         # (doc, vor, score, причина): пары с конфликтом числовых токенов

    def pair_of(self, doc_gid: int):
        return next((p for p in self.pairs if p.doc.gid == doc_gid), None)

    @property
    def ambiguous(self) -> list:
        """Группы без пары, у которых есть кандидаты для LLM (без LLM не решено)."""
        with_candidates = {c.doc.gid for c in self.candidates}
        return [g for g in self.unmatched if g.gid in with_candidates]

    @property
    def absent(self) -> list:
        """Группы без пары и без единого кандидата: только они дают кандидата на missing_in_vor."""
        with_candidates = {c.doc.gid for c in self.candidates}
        return [g for g in self.unmatched if g.gid not in with_candidates]

    def state_of(self, group: Group) -> str:
        if self.pair_of(group.gid):
            return "matched"
        return "ambiguous" if any(c.doc.gid == group.gid for c in self.candidates) else "absent"


class Similarity:
    """Сходство названий: plain (токены как есть) или stemmed (окончания и сокращения-префиксы, config matching.*)."""

    def __init__(self, m: dict):
        self.stemmed = m.get("name_similarity", "plain") == "stemmed"
        self.endings = sorted(m.get("stem_endings", []), key=len, reverse=True)
        self.min_stem = m.get("stem_min_len", 4)
        self.min_prefix = m.get("prefix_abbreviation_min_len", 4)

    def _stem(self, token: str) -> str:
        for ending in self.endings:
            if token.endswith(ending) and len(token) - len(ending) >= self.min_stem:
                return token[: -len(ending)]
        return token

    def _tokens(self, text: str) -> list:
        return [self._stem(t) for t in text.replace("(", " ").replace(")", " ").split()]

    def __call__(self, a: Group, b: Group, drop=()):
        """(token_set_ratio, token_sort_ratio) двух названий; drop: слова, которые не учитываются в сравнении."""
        na, nb = (" ".join(w for w in x.name.split() if w not in drop) for x in (a, b))
        if not self.stemmed:
            return (fuzz.token_set_ratio(na, nb), fuzz.token_sort_ratio(na, nb))
        ta, tb = self._tokens(na), self._tokens(nb)

        def expand(own, other):
            return [next((o for o in other if o != t and len(t) >= self.min_prefix and o.startswith(t)), t) for t in own]

        ta, tb = expand(ta, tb), expand(tb, ta)
        sa, sb = " ".join(ta), " ".join(tb)
        return (fuzz.token_set_ratio(sa, sb), fuzz.token_sort_ratio(sa, sb))


def compute_matching(rows: list, cfg: dict, use_synonyms: bool = True, threshold: float | None = None,
                     missing_side: str | None = None) -> MatchResult:
    m = cfg["rules"]["matching"]
    threshold = m["fuzzy_threshold"] if threshold is None else threshold
    lower, per_row = m["llm_lower_bound"], m["llm_candidates_per_row"]
    subset_below, subset_scope = m["subset_review_below"], m["subset_review_scope"]
    competitor_review = m.get("competitor_review", False)
    ignore_words = set(m.get("candidate_ignore_words", []))
    scores = Similarity(m)
    norm = NameNormalizer(cfg["synonyms"], cfg["rules"], use_synonyms, missing_side)
    groups = build_groups(rows, norm, cfg)
    result = MatchResult(use_synonyms, threshold, norm.missing_side, groups)
    vors = [g for g in groups if g.is_vor]
    docs_ids = sorted({g.doc_id for g in groups if not g.is_vor})

    def comparable(d, v):
        return d.unit_norm is not None and d.unit_norm == v.unit_norm and (d.kind is None or d.kind == v.kind)

    def has_competitor(d, v):
        """Есть ли для строки d другая группа ВОР другого kind, достаточно похожая (путаница работы и материала)."""
        return any(o.gid != v.gid and o.kind != v.kind and comparable(d, o) and scores(d, o)[0] >= lower for o in vors)

    def evaluate(d, v):
        """-> (score, score2, stage или None, конфликты). stage задан, если пару можно слить без ИИ."""
        if d.temp_key == v.temp_key:
            return 100.0, 100.0, "exact", []
        s1, s2 = scores(d, v)
        conflicts = norm.conflicts(d.prepared, v.prepared) if use_synonyms else []
        if use_synonyms and s1 == 100 and s2 < subset_below and (subset_scope == "always" or has_competitor(d, v)):
            conflicts.append(("subset", f"подмножество слов (token_set 100, token_sort {s2:.0f} ниже {subset_below})"))
        if use_synonyms and competitor_review and d.kind is None and s1 >= threshold and has_competitor(d, v):
            conflicts.append(("competitor", f"рядом конкурент другого kind (работа и материал), оценка {s1:.0f}"))
        stage = "fuzzy" if s1 >= threshold and not conflicts else None
        return s1, s2, stage, conflicts

    for doc_id in docs_ids:
        doc_groups = [g for g in groups if g.doc_id == doc_id]
        taken, matched = set(), {}
        for known in (True, False):
            found = []
            for d in doc_groups:
                if d.gid in matched or (d.kind is not None) != known:
                    continue
                for v in vors:
                    if v.gid in taken or not comparable(d, v):
                        continue
                    s1, s2, stage, _ = evaluate(d, v)
                    if stage:
                        if stage == "exact" and d.first.name_norm != v.first.name_norm:
                            stage = "synonyms"       # названия равны только после словаря
                        found.append((s1, s2, -d.gid, -v.gid, d, v, stage))
            found.sort(key=lambda x: x[:4], reverse=True)
            for s1, s2, _, _, d, v, stage in found:
                if d.gid in matched or v.gid in taken:
                    continue
                matched[d.gid] = Pair(d, v, s1, s2, stage)
                taken.add(v.gid)
        result.pairs.extend(matched[g] for g in sorted(matched))
        for d in doc_groups:
            if d.gid in matched:
                continue
            result.unmatched.append(d)
            options = []
            for v in vors:
                if v.gid in taken or not comparable(d, v):
                    continue
                s1, s2, _, conflicts = evaluate(d, v)
                if s1 < lower or (ignore_words and scores(d, v, ignore_words)[0] < lower):
                    continue
                if norm.is_vetoed(conflicts):
                    result.blocked.append((d, v, s1, "; ".join(t for _, t in conflicts)))
                    continue
                why = ("; ".join(t for _, t in conflicts) + f" (score {s1:.0f})" if conflicts
                       else f"score {s1:.0f} в зоне {lower}..{threshold}")
                options.append((s1, s2, -v.gid, Candidate(d, v, s1, why)))
            options.sort(key=lambda x: x[:3], reverse=True)
            result.candidates.extend(c for *_, c in options[:per_row])
    return result
