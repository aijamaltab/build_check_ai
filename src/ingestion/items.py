"""Из разобранного документа в строки единой таблицы items (+ поля staging).

Нормализация: множитель единицы применяется к количеству и цене (quantity хранится после нормализации),
название приводится к name_norm, определяется kind_hint, строится временный work_key
(формат из rules.yaml, matching.work_key_format; окончательный ключ задаёт matching).
Строки с одинаковым ключом внутри документа здесь НЕ суммируются.
"""
from dataclasses import dataclass

from src.normalize import UnitNormalizer, normalize_name

CONTRACT_NAME = "Договор"


@dataclass
class ItemDraft:
    work_name_raw: str
    work_key: str | None
    unit_raw: str | None
    unit_norm: str | None
    quantity: float | None
    unit_price: float | None
    amount: float | None
    doc_date: str | None
    source_row: int
    # staging_items_ext
    quantity_raw: str | None = None
    kind_hint: str | None = None
    name_norm: str | None = None
    currency: str | None = None
    unit_factor: float | None = None
    unit_ok: bool = True
    unit_reason: str = ""
    formula_raw: str | None = None
    drawing_ref: str | None = None
    seq: str | None = None
    price_is_formula: bool = False


def _material_prefixes(tpl: dict) -> tuple:
    prefixes = tpl.get("material_markers", {}).get("drawing_ref_prefixes", [])
    return tuple(p.lower().replace("ё", "е") for p in prefixes)


def build_items(doc, cfg: dict, units: UnitNormalizer | None = None) -> list:
    units = units or UnitNormalizer(cfg["units"])
    iso_date = doc.doc_date.isoformat() if doc.doc_date else None
    if doc.contract is not None:
        if doc.errors:
            return []
        return [ItemDraft(work_name_raw=CONTRACT_NAME, work_key=None, unit_raw=None, unit_norm=None, quantity=None,
                          unit_price=None, amount=doc.total_amount, doc_date=iso_date,
                          source_row=doc.contract["deadline_row"], name_norm=normalize_name(CONTRACT_NAME),
                          currency=doc.currency)]
    tpl = cfg["templates"][doc.template]
    markers = cfg["synonyms"]["strip_markers"]
    key_format = cfg["rules"]["matching"]["work_key_format"]
    prefixes = _material_prefixes(tpl)
    out = []
    for row in doc.rows:
        u = units.parse(row.unit)
        factor = u.factor if u.ok else 1.0
        drawing = (row.drawing_ref or "").lower().replace("ё", "е")
        is_material = (bool(prefixes) and drawing.startswith(prefixes)) or (u.ok and u.is_noun)
        kind = "material" if is_material else "work"
        name_norm = normalize_name(row.name, markers)
        out.append(ItemDraft(
            work_name_raw=row.name,
            work_key=key_format.format(kind=kind, name=name_norm, unit=u.unit_norm or ""),
            unit_raw=row.unit, unit_norm=u.unit_norm if u.ok else None,
            quantity=round(row.quantity * factor, 6),
            unit_price=None if row.unit_price is None else round(row.unit_price / factor, 6),
            amount=row.amount, doc_date=iso_date, source_row=row.source_row,
            quantity_raw=row.quantity_raw, kind_hint=kind, name_norm=name_norm, currency=doc.currency,
            unit_factor=factor, unit_ok=u.ok, unit_reason=u.reason, formula_raw=row.formula_raw,
            drawing_ref=row.drawing_ref, seq=row.seq, price_is_formula=row.price_is_formula))
    return out
