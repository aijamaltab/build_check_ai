"""Нормализация названий для сопоставления и защиты must_match_tokens.

Порядок (config/synonyms.yaml): token_rewrites -> abbreviations и synonyms -> grade_equivalents -> чистка знаков.
В режиме без синонимов (no_synonyms) словарь и защиты выключены: сравниваются сырые name_norm из ingestion
(это базовая линия, сколько находит один rapidfuzz, docs/synthetic_spec.md §8).
"""
import re
from dataclasses import dataclass, field

DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")             # 2,5 -> 2.5
CROSS_SIGN = re.compile(r"(?<=\d)\s?[xх×*]\s?(?=\d)")      # 3х2,5, 3×2,5, 3*2,5 -> одно написание
BRACKETS = re.compile(r"\(([^)]*)\)")
NOT_WORD = re.compile(r"[^\w\s.()]")                         # скобки остаются: текст в скобках часть названия (spec §8: 85,7)
LOOSE_DOT = re.compile(r"(?<!\d)\.|\.(?!\d)")              # точка не между цифрами (кл., тяж.) убирается


def _word_re(word: str) -> re.Pattern:
    """Слово или сокращение целиком; если оно кончается точкой, правая граница не нужна."""
    tail = "" if word.endswith(".") else r"(?!\w)"
    return re.compile(r"(?<!\w)" + re.escape(word) + tail)


@dataclass
class Prepared:
    """Название, подготовленное к сравнению."""
    text: str                                              # чистый текст для rapidfuzz
    brackets: list = field(default_factory=list)          # тексты в скобках (отсортированы)
    tokens: dict = field(default_factory=dict)            # шаблон -> отсортированные токены
    words: list = field(default_factory=list)             # по каждой группе: найденные основы слов


class NameNormalizer:
    def __init__(self, synonyms_cfg: dict, rules_cfg: dict, use_synonyms: bool = True, missing_side: str | None = None):
        self.use_synonyms = use_synonyms
        guards = rules_cfg["matching"]["must_match_tokens"]
        self.patterns = guards["patterns"]
        self.groups = guards["exclusive_word_groups"]
        self.bracket_rule = guards["bracket_text"]
        self.missing_side = missing_side or guards.get("missing_side", "block")
        self.veto_keys = guards.get("llm_veto", ["patterns"])
        self._rewrites = [(re.compile(p), r) for p, r in synonyms_cfg.get("token_rewrites", [])]
        self._abbr = [(_word_re(k.lower()), v) for k, v in synonyms_cfg.get("abbreviations", {}).items()]
        self._syn = [(_word_re(v.lower()), canon) for canon, variants in synonyms_cfg.get("synonyms", {}).items()
                     for v in variants]
        self._grades = [(_word_re(k.lower()), v) for k, v in synonyms_cfg.get("grade_equivalents", {}).items()]

    def prepare(self, name_norm: str) -> Prepared:
        s = DECIMAL_COMMA.sub(".", name_norm)
        s = CROSS_SIGN.sub("х", s)
        if self.use_synonyms:
            for pat, rep in self._rewrites:
                s = pat.sub(rep, s)
            for pat, rep in self._abbr + self._syn + self._grades:
                s = pat.sub(rep, s)
        brackets = sorted(re.sub(r"\s+", " ", b).strip() for b in BRACKETS.findall(s))
        text = NOT_WORD.sub(" ", s)
        text = re.sub(r"\s+", " ", LOOSE_DOT.sub(" ", text)).strip()
        text = re.sub(r"\s*\(\s*", " (", text)
        text = re.sub(r"\s*\)", ")", text)
        prep = Prepared(text=text, brackets=brackets)
        prep.tokens = {p: sorted(re.findall(p, text)) for p in self.patterns}
        prep.words = [sorted(w for w in group if w in text) for group in self.groups]
        return prep

    def conflicts(self, a: Prepared, b: Prepared) -> list:
        """Причины, по которым пару нельзя слить без ИИ: список (вид, текст). Пустой список = защиты пройдены.
        Вид 'patterns' (числовые токены) ИИ обойти не может, 'words' и 'brackets' решает ИИ."""
        out = []
        for p in self.patterns:
            ta, tb = a.tokens[p], b.tokens[p]
            if ta != tb and (self.missing_side == "block" or (ta and tb)):
                out.append(("patterns", f"{p}: {ta} против {tb}"))
        for wa, wb in zip(a.words, b.words):
            if wa != wb and (self.missing_side == "block" or (wa and wb)):
                out.append(("words", f"слова группы: {wa} против {wb}"))
        if self.bracket_rule == "must_equal" and a.brackets != b.brackets and (
                self.missing_side == "block" or (a.brackets and b.brackets)):
            out.append(("brackets", f"текст в скобках: {a.brackets} против {b.brackets}"))
        return out

    def is_vetoed(self, conflicts: list) -> bool:
        return any(kind in self.veto_keys for kind, _ in conflicts)
