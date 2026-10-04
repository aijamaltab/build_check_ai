"""Строки items -> группы одного ключа внутри документа (шаг 1 matching).

Строки с одинаковым ключом (kind-признак, нормализованное название, единица) внутри документа суммируются,
«Строительный мусор» это один ключ. Полный дубль строки (название, единица, количество, формула, а у шаблонов
с allow_repeated_names ещё и сумма) в сумму не входит: он остаётся в группе с пометкой counted = 0.
ВОР агрегируется по проекту целиком (оба файла ВОР вместе), остальные документы по одному.
"""
from dataclasses import dataclass, field

from .names import NameNormalizer, Prepared

LOAD_SQL = """
SELECT i.item_id, i.doc_id, i.doc_type, i.source_file, i.source_sheet, i.source_row, i.work_name_raw, i.unit_raw,
       i.unit_norm, i.quantity, i.amount, e.name_norm, e.kind_hint, e.quantity_raw, e.formula_raw, s.template
FROM items i
JOIN staging_items_ext e ON e.item_id = i.item_id
JOIN staging_documents_ext s ON s.doc_id = i.doc_id
WHERE i.project_id = ? AND i.doc_type != 'contract'
ORDER BY i.doc_id, i.source_row
"""


@dataclass
class Row:
    item_id: int
    doc_id: int
    doc_type: str
    file: str
    sheet: str
    source_row: int
    name_raw: str
    unit_raw: str | None
    unit_norm: str | None
    quantity: float | None
    amount: float | None
    name_norm: str
    kind_hint: str
    quantity_raw: str | None
    formula_raw: str | None
    template: str | None


@dataclass
class Group:
    gid: int
    doc_id: int | None            # None у групп ВОР (они собраны по проекту)
    doc_type: str
    name: str                     # текст для сравнения (после словаря в режиме synonyms)
    unit_norm: str | None
    kind: str | None              # у ВОР известен всегда; вне ВОР признак: material или None
    prepared: Prepared
    rows: list = field(default_factory=list)
    counted: dict = field(default_factory=dict)          # item_id -> 1 если строка входит в сумму
    qty_sum: float = 0.0

    @property
    def first(self) -> Row:
        return self.rows[0]

    @property
    def is_vor(self) -> bool:
        return self.doc_type == "vor"

    @property
    def temp_key(self) -> tuple:
        return (self.name, self.unit_norm)


def load_rows(conn, project_id: str) -> list:
    return [Row(*tuple(r)) for r in conn.execute(LOAD_SQL, (project_id,))]


def dup_key(row: Row, cfg: dict) -> tuple:
    key = (row.name_norm, row.unit_raw, row.quantity_raw, row.formula_raw)
    repeated = cfg["templates"].get(row.template or "", {}).get("allow_repeated_names")
    return key + (row.amount,) if repeated else key


def build_groups(rows: list, norm: NameNormalizer, cfg: dict) -> list:
    """-> список групп: сначала ВОР, затем остальные документы по порядку."""
    by_key, groups, seen_dups = {}, [], set()
    for row in rows:
        prep = norm.prepare(row.name_norm)
        if row.doc_type == "vor":
            kind = row.kind_hint                       # в ВОР kind известен: «спец.» или единица-существительное, иначе работа
            scope = None
        else:
            kind = "material" if row.kind_hint == "material" else None   # вне ВОР «work» значит «признака нет»
            scope = row.doc_id
        key = (scope, kind, prep.text, row.unit_norm)
        group = by_key.get(key)
        if group is None:
            group = Group(len(groups), scope, row.doc_type, prep.text, row.unit_norm, kind, prep)
            by_key[key] = group
            groups.append(group)
        dk = (row.doc_id,) + dup_key(row, cfg)
        counted = dk not in seen_dups
        seen_dups.add(dk)
        group.rows.append(row)
        group.counted[row.item_id] = 1 if counted else 0
        if counted and row.quantity is not None:
            group.qty_sum += row.quantity
    groups.sort(key=lambda g: (not g.is_vor, g.first.doc_id, g.first.source_row))
    for i, g in enumerate(groups):
        g.gid = i
    return groups
