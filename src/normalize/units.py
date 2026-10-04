"""Нормализация единиц измерения по config/units.yaml.

Порядок разбора (см. комментарий в units.yaml):
  1) отделить множитель в начале строки («100 м2» -> 100, «м2»);
  2) остаток привести к виду «без пробелов и точек, нижний регистр» и найти единицу
     (самое длинное совпадение с начала, остаток должен быть в qualifiers);
  3) неизвестное -> ok=False (dq «единица известна»).
"""
import re
from dataclasses import dataclass


def clean_unit(s) -> str:
    """lower, ё -> е, без пробелов и точек: так сравниваются и варианты из конфига, и значение из файла."""
    return str(s).lower().replace("ё", "е").replace(".", "").replace("\xa0", " ").replace(" ", "")


@dataclass(frozen=True)
class UnitResult:
    ok: bool
    unit_norm: str | None = None
    factor: float = 1.0
    is_noun: bool = False
    reason: str = ""


class UnitNormalizer:
    def __init__(self, units_cfg: dict):
        self._mult_re = re.compile(units_cfg["multiplier"]["pattern"])
        self._factors = {float(x) for x in units_cfg["multiplier"]["allowed_factors"]}
        self._qualifiers = {clean_unit(q) for q in units_cfg.get("qualifiers", [])}
        variants = []
        for canon, names in units_cfg["units"].items():
            variants += [(clean_unit(v), canon, False) for v in names]
        for canon, names in units_cfg.get("noun_units", {}).items():
            variants += [(clean_unit(v), canon, True) for v in names]
        # длинные варианты первыми (sorted стабилен: на равной длине обычные единицы раньше существительных)
        self._variants = sorted(variants, key=lambda v: -len(v[0]))

    def parse(self, text) -> UnitResult:
        if text is None or not str(text).strip():
            return UnitResult(False, reason="единица пустая")
        text = str(text).strip()
        factor, rest = 1.0, text
        m = self._mult_re.match(text)
        if m:
            factor = float(m.group(1).replace(",", "."))
            rest = m.group(2)
            if factor not in self._factors:
                return UnitResult(False, reason=f"множитель {m.group(1)} не из списка")
        cleaned = clean_unit(rest)
        for variant, canon, is_noun in self._variants:
            if cleaned.startswith(variant):
                tail = cleaned[len(variant):]
                if not tail or tail in self._qualifiers:
                    return UnitResult(True, canon, factor, is_noun)
        return UnitResult(False, reason=f"единица «{text}» неизвестна")
