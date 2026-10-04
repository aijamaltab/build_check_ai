"""Чтение Excel по config/templates.yaml в «сырые» строки (staging) без нормализации единиц.

Что делает:
  * определяет шаблон по header_keywords (строка шапки ищется по словам, а не по номеру строки);
  * читает колонки по названиям из шаблона (безымянные колонки и дубль колонки игнорируются);
  * пропускает пустые строки, строку номеров «1 2 3 4 5», разделы, итоги и подписи;
  * формулы читает с data_only=True; если у формулы нет кэшированного значения, строка не считается молча.
Единицы, множители и названия нормализует src/ingestion/items.py.
"""
import datetime as dt
import re
from dataclasses import dataclass, field

from openpyxl import load_workbook

from src.normalize import find_date_in_text, normalize_header, parse_date, parse_number

HEADER_SCAN_ROWS = 100       # дальше этой строки шапку не ищем
REQUIRED_FIELDS = ("work_name_raw", "unit_raw", "quantity")


@dataclass
class RawRow:
    source_row: int
    name: str | None
    unit: str | None
    quantity: float | None
    quantity_raw: str | None
    unit_price: float | None = None
    amount: float | None = None
    formula_raw: str | None = None
    drawing_ref: str | None = None
    seq: str | None = None
    price_is_formula: bool = False


@dataclass
class ParsedDoc:
    file_name: str
    sheet: str
    template: str | None
    doc_type: str | None
    rows: list = field(default_factory=list)
    unrecognized: list = field(default_factory=list)      # (номер строки, причина)
    formula_missing: list = field(default_factory=list)   # номера строк: формула без кэшированного значения
    errors: list = field(default_factory=list)            # шаблон/колонки/поля не найдены
    doc_date: dt.date | None = None
    date_row: int | None = None
    total_amount: float | None = None                     # итоговая строка документа (в items не попадает)
    total_row: int | None = None
    currency: str | None = None
    has_amount_column: bool = False
    allow_repeated_names: bool = False
    n_service: int = 0                                    # пустые, номера колонок, разделы, итоги, подписи
    contract: dict | None = None                          # для договора: deadline, deadline_row, total_amount, total_row


# ---------- вспомогательное ----------
def _text(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _raw_text(v) -> str | None:
    """Исходное значение ячейки как текст: 12.0 -> «12», 0.06 -> «0.06»."""
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip() or None


def _word_start_search(keyword: str, text: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(keyword.lower().replace("ё", "е")), text.lower().replace("ё", "е")) is not None


def _read_sheet(source):
    """-> (имя листа, значения с data_only=True, те же ячейки без data_only для признака формулы)."""
    wb_v = load_workbook(source, data_only=True)
    if hasattr(source, "seek"):
        source.seek(0)
    wb_f = load_workbook(source)
    ws_v, ws_f = wb_v.worksheets[0], wb_f.worksheets[0]
    values = [list(r) for r in ws_v.iter_rows(values_only=True)]
    formulas = [[c.data_type == "f" for c in r] for r in ws_f.iter_rows()]
    return ws_v.title, values, formulas


def _find_header(values, tpl):
    """Индекс строки шапки: первая строка, где есть ВСЕ header_keywords шаблона."""
    keywords = [normalize_header(k) for k in tpl["header_keywords"]]
    for idx, row in enumerate(values[:HEADER_SCAN_ROWS]):
        line = " | ".join(normalize_header(c) for c in row if c is not None and str(c).strip())
        if keywords and all(k in line for k in keywords):
            return idx
    return None


def detect_template(values, templates):
    """-> (имя шаблона, индекс строки шапки) или (None, None). При нескольких совпадениях выигрывает шаблон
    с большим числом ключевых слов, затем первый в конфиге."""
    best = None
    for name, tpl in templates.items():
        if "header_keywords" not in tpl:
            continue
        idx = _find_header(values, tpl)
        if idx is not None and (best is None or len(tpl["header_keywords"]) > best[2]):
            best = (name, idx, len(tpl["header_keywords"]))
    return (best[0], best[1]) if best else (None, None)


def _detect_contract(values, templates):
    for name, tpl in templates.items():
        if tpl.get("layout") != "key_value":
            continue
        labels = {normalize_header(c) for row in values for c in row[:1] if c is not None}
        if all(any(normalize_header(v) in labels for v in variants) for variants in tpl["fields"].values()):
            return name
    return None


def _resolve_columns(tpl, header):
    """поле -> список индексов колонок (у названия при дубле колонки их несколько)."""
    starts = tpl.get("column_match") == "starts_with"
    head = [normalize_header(c) if c is not None else "" for c in header]
    taken, result = set(), {}
    for fld, variants in tpl["columns"].items():
        vs = [normalize_header(v) for v in variants]
        cols = [i for i, h in enumerate(head)
                if h and i not in taken and any(h.startswith(v) if starts else h == v for v in vs)]
        if fld != "work_name_raw" or not tpl.get("drop_duplicate_adjacent_columns"):
            cols = cols[:1]          # дубль колонки читаем один раз
        taken.update(cols)
        if cols:
            result[fld] = cols
    return result


def _detect_currency(tpl, header, columns, default):
    cfg = tpl.get("currency_from_header_text")
    if not cfg:
        return default
    for fld in cfg["columns"]:
        for col in columns.get(fld, []):
            m = re.search(cfg["pattern"], str(header[col] or ""), flags=re.I)
            if m:
                return default if m.group(0).lower() == "сом" else m.group(0).upper()
    return default


def _find_date(values, header_idx, tpl):
    """Дата акта: по doc_date_regex в строках над шапкой или отдельной ячейкой над шапкой (act_c)."""
    for r in range(header_idx):
        for v in values[r]:
            if v is None:
                continue
            if tpl.get("doc_date_regex"):
                d = find_date_in_text(v, tpl["doc_date_regex"])
            elif tpl.get("date_cell_above_header"):
                d = parse_date(v) if not isinstance(v, (int, float)) else None
            else:
                d = None
            if d:
                return d, r + 1
    return None, None


# ---------- таблицы ----------
def _parse_table(doc, values, formulas, header_idx, tpl, cfg):
    columns = _resolve_columns(tpl, values[header_idx])
    missing = [f for f in REQUIRED_FIELDS if f not in columns]
    if missing:
        doc.errors.append("колонки не найдены: " + ", ".join(missing))
        return
    doc.currency = _detect_currency(tpl, values[header_idx], columns, cfg["rules"]["currency"]["default"])
    doc.has_amount_column = "amount" in columns
    doc.allow_repeated_names = bool(tpl.get("allow_repeated_names"))
    doc.doc_date, doc.date_row = _find_date(values, header_idx, tpl)
    skip_keywords = tpl.get("skip_row_keywords", [])
    skip_patterns = [re.compile(p) for p in tpl.get("skip_row_patterns", [])]
    marker_cols = columns.get("drawing_ref")

    def cell(vals, fld):
        cols = columns.get(fld)
        return vals[cols[0]] if cols and cols[0] < len(vals) else None

    def is_formula(r, fld):
        cols = columns.get(fld)
        return bool(cols and cols[0] < len(formulas[r]) and formulas[r][cols[0]])

    for r in range(header_idx + 1, len(values)):
        vals, rownum = values[r], r + 1
        non_empty = [str(v).strip() for v in vals if v is not None and str(v).strip()]
        if not non_empty:
            doc.n_service += 1
            continue
        name = None
        for col in columns["work_name_raw"]:             # при дубле колонки берём первую непустую
            name = name or (_text(vals[col]) if col < len(vals) else None)
        unit, qty_cell = _text(cell(vals, "unit_raw")), cell(vals, "quantity")
        qty_empty = qty_cell is None or not str(qty_cell).strip()
        # строка номеров колонок «1 2 3 4 5»
        if any(p.match(" ".join(non_empty)) for p in skip_patterns):
            doc.n_service += 1
            continue
        # итоги и подписи: ключевые слова в названии или в первой непустой ячейке
        probes = [name or "", non_empty[0]]
        if any(_word_start_search(k, p) for k in skip_keywords for p in probes):
            amount = parse_number(cell(vals, "amount"))
            if amount is not None:
                doc.total_amount, doc.total_row = amount, rownum
            doc.n_service += 1
            continue
        # раздел или подзаголовок: нет единицы и нет количества
        if not unit and qty_empty:
            doc.n_service += 1
            continue
        # дальше строка позиции: любая проблема с ней это «не распознано», а не молчаливый пропуск
        bad = None
        for fld in ("quantity", "unit_price", "amount"):
            if is_formula(r, fld) and cell(vals, fld) is None:
                doc.formula_missing.append(rownum)
                bad = bad or f"формула без значения в колонке «{fld}»"
        if bad is None and not name:
            bad = "нет названия"
        quantity = parse_number(qty_cell)
        if bad is None and quantity is None:
            bad = "нет количества" if qty_empty else f"количество не число: «{qty_cell}»"
        price, amount = None, None
        for fld in ("unit_price", "amount"):
            raw = cell(vals, fld)
            num = parse_number(raw)
            if bad is None and raw is not None and str(raw).strip() and num is None:
                bad = f"«{fld}» не число: «{raw}»"
            if fld == "unit_price":
                price = num
            else:
                amount = num
        if bad:
            doc.unrecognized.append((rownum, bad))
            continue
        doc.rows.append(RawRow(
            source_row=rownum, name=name, unit=unit, quantity=quantity, quantity_raw=_raw_text(qty_cell),
            unit_price=price, amount=amount,
            formula_raw=_text(cell(vals, "formula_raw")), seq=_raw_text(cell(vals, "seq")),
            drawing_ref=_text(vals[marker_cols[0]]) if marker_cols and marker_cols[0] < len(vals) else None,
            price_is_formula=is_formula(r, "unit_price")))


# ---------- договор ----------
def _parse_contract(doc, values, tpl):
    found = {}
    for r, row in enumerate(values):
        label = normalize_header(row[0]) if row and row[0] is not None else ""
        for fld, variants in tpl["fields"].items():
            if fld not in found and label in {normalize_header(v) for v in variants}:
                found[fld] = (r + 1, row[1] if len(row) > 1 else None)
    deadline_row, deadline = found["deadline"]
    total_row, total = found["total_amount"]
    doc.doc_date, doc.date_row = parse_date(deadline), deadline_row
    doc.total_amount, doc.total_row = parse_number(total), total_row
    if doc.doc_date is None:
        doc.errors.append(f"срок договора не распознан: «{deadline}»")
    if doc.total_amount is None:
        doc.errors.append(f"сумма договора не распознана: «{total}»")
    doc.contract = {"deadline_row": deadline_row, "total_row": total_row}


# ---------- вход ----------
def parse_workbook(source, file_name: str, cfg: dict) -> ParsedDoc:
    """source: путь или файловый объект. Шаблон определяется по содержимому."""
    sheet, values, formulas = _read_sheet(source)
    doc = ParsedDoc(file_name=file_name, sheet=sheet, template=None, doc_type=None)
    name, header_idx = detect_template(values, cfg["templates"])
    if name:
        tpl = cfg["templates"][name]
        doc.template, doc.doc_type = name, tpl["doc_type"]
        _parse_table(doc, values, formulas, header_idx, tpl, cfg)
        return doc
    name = _detect_contract(values, cfg["templates"])
    if name:
        tpl = cfg["templates"][name]
        doc.template, doc.doc_type = name, tpl["doc_type"]
        doc.currency = cfg["rules"]["currency"]["default"]
        _parse_contract(doc, values, tpl)
        return doc
    doc.errors.append("шаблон не определён: нет строки шапки по header_keywords ни у одного шаблона")
    return doc
