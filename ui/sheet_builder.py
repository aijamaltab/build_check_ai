"""Построение модели данных для Google Sheets Lookalike (интерактивный аудит исходных документов).

Task 1.1: Экстрактор сырой сетки документа (openpyxl data_only=False/True, формулы, bounding box)
Task 1.2: Слой аннотаций расхождений (Mapping Issues -> Cells, linked_ref target_jump)
Task 1.3: Агрегация статусов и счетчиков для вкладок
"""
import datetime as dt
from pathlib import Path
from typing import Any
import pandas as pd
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from src.config import load_config
from src.ingestion.parse import detect_template
from src.normalize import normalize_header
from ui.data import TYPE_RU, connect_readonly, fmt_num, fmt_pct

DOC_TITLES = {
    "vor_1.xlsx": "ВОР №1",
    "vor_2.xlsx": "ВОР №2",
    "estimate.xlsx": "Смета",
    "contract.xlsx": "Договор",
    "act_1.xlsx": "Акт №1",
    "act_2.xlsx": "Акт №2",
    "act_3.xlsx": "Акт №3",
    "act_4.xlsx": "Акт №4",
    "act_5.xlsx": "Акт №5",
}


def sanitize_doc_id(file_name: str) -> str:
    """Идентификатор вкладки без расширения и спецсимволов."""
    return Path(file_name).stem.replace("-", "_").replace(" ", "_")


def fmt_som_str(val: Any) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{fmt_num(val)} сом"


def fmt_qty_str(val: Any, unit: str = "") -> str:
    if val is None or pd.isna(val):
        return "—"
    num = fmt_num(val)
    return f"{num} {unit}".strip() if unit else num


def format_cell_value(val: Any) -> str:
    """Форматирование значения для отображения в ячейке."""
    if val is None:
        return ""
    if isinstance(val, (dt.datetime, dt.date)):
        return val.strftime("%d.%m.%Y")
    if isinstance(val, float):
        if val.is_integer():
            return f"{int(val):,}".replace(",", " ")
        # Ограничиваем дробную часть до 2-4 знаков
        formatted = f"{val:,.2f}".replace(",", " ")
        if formatted.endswith(".00"):
            return formatted[:-3]
        return formatted
    if isinstance(val, int):
        return f"{val:,}".replace(",", " ")
    return str(val).strip()


def extract_sheet_grid(source: Path | str | Any, sheet_name: str | None = None) -> dict:
    """Task 1.1: Читает Excel через openpyxl с формулами и значениями, отсекает пустые хвосты.

    Возвращает структуру:
    {
        "columns": ["A", "B", ...],
        "rows": [{"row_num": 1, "cells": {"A": {"value": ..., "formula": ..., ...}, ...}}],
        "max_row": int,
        "max_col": int
    }
    """
    if hasattr(source, "seek"):
        source.seek(0)
    wb_v = load_workbook(source, data_only=True)
    if hasattr(source, "seek"):
        source.seek(0)
    wb_f = load_workbook(source, data_only=False)

    ws_v = wb_v[sheet_name] if sheet_name and sheet_name in wb_v.sheetnames else wb_v.worksheets[0]
    ws_f = wb_f[sheet_name] if sheet_name and sheet_name in wb_f.sheetnames else wb_f.worksheets[0]

    # Ищем значащий диапазон (bounding box)
    max_r = 0
    max_c = 0
    raw_cells_v = {}
    raw_cells_f = {}

    for r_idx, (row_v, row_f) in enumerate(zip(ws_v.iter_rows(), ws_f.iter_rows(), strict=False), start=1):
        for c_idx, (cell_v, cell_f) in enumerate(zip(row_v, row_f, strict=False), start=1):
            val_v = cell_v.value
            val_f = cell_f.value
            has_val = val_v is not None and str(val_v).strip() != ""
            has_form = val_f is not None and (cell_f.data_type == "f" or str(val_f).startswith("="))
            if has_val or has_form:
                if r_idx > max_r:
                    max_r = r_idx
                if c_idx > max_c:
                    max_c = c_idx
            raw_cells_v[(r_idx, c_idx)] = val_v
            raw_cells_f[(r_idx, c_idx)] = (cell_f, val_f)

    if max_r == 0 or max_c == 0:
        return {"columns": [], "rows": [], "max_row": 0, "max_col": 0}

    columns = [get_column_letter(c) for c in range(1, max_c + 1)]
    rows = []

    for r in range(1, max_r + 1):
        row_cells = {}
        for c in range(1, max_c + 1):
            col_letter = columns[c - 1]
            val = raw_cells_v.get((r, c))
            cell_f_obj, val_f = raw_cells_f.get((r, c), (None, None))

            formula = None
            if cell_f_obj is not None:
                if cell_f_obj.data_type == "f" or (val_f is not None and str(val_f).startswith("=")):
                    formula = str(val_f)

            # Безопасное сериализуемое значение
            safe_val = val
            if isinstance(val, (dt.datetime, dt.date)):
                safe_val = val.strftime("%d.%m.%Y")

            row_cells[col_letter] = {
                "value": safe_val,
                "formula": formula,
                "display": format_cell_value(val),
                "status": None,
                "issue": None,
                "ai_match": None,
            }
        rows.append({"row_num": r, "cells": row_cells})

    return {
        "columns": columns,
        "rows": rows,
        "max_row": max_r,
        "max_col": max_c,
    }


def detect_doc_columns(grid: dict, templates: dict) -> dict:
    """Определяет строку заголовков и сопоставляет поля шаблона с буквами колонок."""
    rows_values = []
    for r in grid.get("rows", []):
        r_vals = [r["cells"][col]["value"] for col in grid.get("columns", [])]
        rows_values.append(r_vals)

    tpl_name, h_idx = detect_template(rows_values, templates)
    if not tpl_name or h_idx is None:
        # Проверяем договор key_value
        return {"template": None, "header_row": None, "columns": {}}

    tpl = templates[tpl_name]
    header = [normalize_header(c) if c else "" for c in rows_values[h_idx]]
    cols_map = {}
    for fld, variants in tpl.get("columns", {}).items():
        for v in variants:
            nv = normalize_header(v)
            if nv in header:
                c_idx = header.index(nv)
                cols_map[fld] = grid["columns"][c_idx]
                break

    return {
        "template": tpl_name,
        "header_row": h_idx + 1,  # 1-based
        "columns": cols_map,
    }


def build_sheet_audit_model(files_dir: Path | str, db_path: Path | str, project_id: str = "demo") -> dict:
    """Task 1.1 + 1.2 + 1.3: Формирует полную модель данных для экрана Google Sheets Lookalike.

    Сопоставляет сетки ячеек всех документов с issues_view и matches,
    проставляет target_jump ссылки, статусы critical/warning/ai и счетчики вкладок.
    """
    files_dir = Path(files_dir)
    cfg = load_config()
    templates = cfg.get("templates", {})

    conn = connect_readonly(db_path)
    try:
        issues_df = pd.read_sql_query("SELECT * FROM issues_view WHERE project_id = ?", conn, params=(project_id,))
        items_df = pd.read_sql_query("SELECT * FROM items WHERE project_id = ?", conn, params=(project_id,))
        docs_df = pd.read_sql_query("SELECT * FROM documents WHERE project_id = ?", conn, params=(project_id,))
        ai_matches_df = pd.read_sql_query(
            """
            SELECT m.work_key, e.stage, e.reason, e.confidence,
                   i.source_file, i.source_row, i.work_name_raw AS doc_name,
                   v.source_file AS vor_file, v.source_row AS vor_row, v.work_name_raw AS vor_name
            FROM matches m
            JOIN staging_matches_ext e ON e.match_id = m.match_id
            JOIN items i ON i.item_id = m.item_id
            JOIN items v ON v.item_id = m.matched_to_item_id
            WHERE i.project_id = ? AND e.stage IN ('llm', 'llm_row')
            """,
            conn,
            params=(project_id,),
        )
    finally:
        conn.close()

    # Извлекаем сетки для каждого документа
    sheets = {}
    col_mappings = {}
    doc_order = {"vor": 0, "estimate": 1, "contract": 2, "act": 3}

    # Сортируем документы
    doc_files = []
    for _, doc_row in docs_df.iterrows():
        fname = doc_row["file_name"]
        fpath = files_dir / fname
        if fpath.exists():
            doc_files.append((doc_row["doc_type"], fname, fpath))
    doc_files.sort(key=lambda x: (doc_order.get(x[0], 99), x[1]))

    for doc_type, fname, fpath in doc_files:
        doc_id = sanitize_doc_id(fname)
        grid = extract_sheet_grid(fpath)
        col_map = detect_doc_columns(grid, templates)
        col_mappings[fname] = col_map

        title = DOC_TITLES.get(fname, fname)
        grid["doc_id"] = doc_id
        grid["file_name"] = fname
        grid["title"] = title
        grid["doc_type"] = doc_type
        sheets[doc_id] = grid

    # Индексируем items по (doc_type, work_key) и (source_file, source_row)
    items_by_key = {}
    for _, it in items_df.iterrows():
        k = (it["doc_type"], it["work_key"])
        items_by_key.setdefault(k, []).append(it)

    # 1. Аннотируем прямые расхождения (Issues)
    for _, iss in issues_df.iterrows():
        itype = iss["issue_type"]
        s_file = iss["source_file"]
        s_row = int(iss["source_row"]) if pd.notna(iss["source_row"]) else None
        sev = iss["severity"]
        doc_id = sanitize_doc_id(s_file)

        if doc_id not in sheets or s_row is None:
            continue

        sheet_obj = sheets[doc_id]
        cols_map = col_mappings.get(s_file, {}).get("columns", {})

        # Определяем целевую колонку для подсветки расхождения
        target_col = None
        if itype == "volume_exceeded":
            target_col = cols_map.get("quantity", "D")
        elif itype == "price_increase":
            target_col = cols_map.get("unit_price", "E")
        elif itype == "missing_in_vor":
            target_col = cols_map.get("work_name_raw", "B")
        elif itype == "late_act":
            # Дата акта в заголовке
            target_col = "A" if "A" in sheet_obj["columns"] else sheet_obj["columns"][0]
        else:
            target_col = cols_map.get("work_name_raw", "B")

        if target_col not in sheet_obj["columns"]:
            target_col = sheet_obj["columns"][0]

        # Находим строку в сетке
        row_dict = None
        for r_entry in sheet_obj["rows"]:
            if r_entry["row_num"] == s_row:
                row_dict = r_entry["cells"]
                break

        if not row_dict or target_col not in row_dict:
            continue

        # Формируем target_jump
        target_jump = None
        wk = iss["work_key"]

        if itype == "volume_exceeded":
            vor_matches = items_by_key.get(("vor", wk), [])
            if vor_matches:
                v_it = vor_matches[0]
                v_file = v_it["source_file"]
                v_row = int(v_it["source_row"])
                v_doc_id = sanitize_doc_id(v_file)
                v_col = col_mappings.get(v_file, {}).get("columns", {}).get("quantity", "D")
                target_jump = {
                    "doc_id": v_doc_id,
                    "cell": f"{v_col}{v_row}",
                    "title": DOC_TITLES.get(v_file, v_file),
                    "row": v_row,
                    "col": v_col,
                }
                # Добавляем обратную аннотацию в ВОР!
                if v_doc_id in sheets:
                    v_sheet = sheets[v_doc_id]
                    for vr in v_sheet["rows"]:
                        if vr["row_num"] == v_row and v_col in vr["cells"]:
                            v_cell = vr["cells"][v_col]
                            if v_cell["status"] != "critical":
                                v_cell["status"] = "critical"
                                v_cell["issue"] = {
                                    "id": f"REV-{iss['issue_id']}",
                                    "type": "volume_exceeded_ref",
                                    "title": "Превышение по актам",
                                    "severity": "critical",
                                    "plan": fmt_qty_str(iss["expected"], iss.get("unit_norm") or iss.get("unit") or ""),
                                    "fact": fmt_qty_str(iss["actual"], iss.get("unit_norm") or iss.get("unit") or ""),
                                    "delta": f"+{fmt_qty_str(iss['delta'], iss.get('unit_norm') or iss.get('unit') or '')} (+{iss['delta_pct']:.0f}%)",
                                    "impact_som": fmt_som_str(iss["impact_som"]),
                                    "explanation": f"Позиция превышена накопительно в актах (например, {DOC_TITLES.get(s_file, s_file)}).",
                                    "target_jump": {
                                        "doc_id": doc_id,
                                        "cell": f"{target_col}{s_row}",
                                        "title": DOC_TITLES.get(s_file, s_file),
                                        "row": s_row,
                                        "col": target_col,
                                    },
                                }
                            break

        elif itype == "price_increase":
            est_matches = items_by_key.get(("estimate", wk), [])
            if est_matches:
                e_it = est_matches[0]
                e_file = e_it["source_file"]
                e_row = int(e_it["source_row"])
                e_doc_id = sanitize_doc_id(e_file)
                e_col = col_mappings.get(e_file, {}).get("columns", {}).get("unit_price", "F")
                target_jump = {
                    "doc_id": e_doc_id,
                    "cell": f"{e_col}{e_row}",
                    "title": DOC_TITLES.get(e_file, e_file),
                    "row": e_row,
                    "col": e_col,
                }
                # Добавляем обратную аннотацию в смету!
                if e_doc_id in sheets:
                    e_sheet = sheets[e_doc_id]
                    for er in e_sheet["rows"]:
                        if er["row_num"] == e_row and e_col in er["cells"]:
                            e_cell = er["cells"][e_col]
                            if e_cell["status"] != "critical":
                                e_cell["status"] = "critical"
                                e_cell["issue"] = {
                                    "id": f"REV-{iss['issue_id']}",
                                    "type": "price_increase_ref",
                                    "title": "Завышение расценки в акте",
                                    "severity": "critical",
                                    "plan": f"{fmt_som_str(iss['expected'])} / ед.",
                                    "fact": f"{fmt_som_str(iss['actual'])} / ед.",
                                    "delta": f"+{fmt_som_str(iss['delta'])} (+{iss['delta_pct']:.0f}%)",
                                    "impact_som": fmt_som_str(iss["impact_som"]),
                                    "explanation": f"В акте {DOC_TITLES.get(s_file, s_file)} применена завышенная цена.",
                                    "target_jump": {
                                        "doc_id": doc_id,
                                        "cell": f"{target_col}{s_row}",
                                        "title": DOC_TITLES.get(s_file, s_file),
                                        "row": s_row,
                                        "col": target_col,
                                    },
                                }
                            break

        elif itype == "late_act":
            con_matches = items_by_key.get(("contract", "contract"), []) or [it for _, it in items_df.iterrows() if it["doc_type"] == "contract"]
            if con_matches:
                c_it = con_matches[0]
                c_file = c_it["source_file"]
                c_row = int(c_it["source_row"]) if pd.notna(c_it["source_row"]) else 6
                c_doc_id = sanitize_doc_id(c_file)
                c_col = "B"
                target_jump = {
                    "doc_id": c_doc_id,
                    "cell": f"{c_col}{c_row}",
                    "title": DOC_TITLES.get(c_file, c_file),
                    "row": c_row,
                    "col": c_col,
                }
                # Обратная аннотация в договоре
                if c_doc_id in sheets:
                    c_sheet = sheets[c_doc_id]
                    for cr in c_sheet["rows"]:
                        if cr["row_num"] == c_row and c_col in cr["cells"]:
                            c_cell = cr["cells"][c_col]
                            c_cell["status"] = "critical"
                            c_cell["issue"] = {
                                "id": f"REV-{iss['issue_id']}",
                                "type": "late_act_ref",
                                "title": "Акт подписан после срока",
                                "severity": "critical",
                                "plan": str(iss["expected_text"] or "Срок по договору"),
                                "fact": str(iss["actual_text"] or "Дата акта"),
                                "delta": f"+{int(iss['delta'])} дн.",
                                "impact_som": "—",
                                "explanation": f"Акт {DOC_TITLES.get(s_file, s_file)} датирован позже установленного срока.",
                                "target_jump": {
                                    "doc_id": doc_id,
                                    "cell": f"{target_col}{s_row}",
                                    "title": DOC_TITLES.get(s_file, s_file),
                                    "row": s_row,
                                    "col": target_col,
                                },
                            }
                            break

        # Заполняем ячейку в текущем акте
        cell = row_dict[target_col]
        status = "critical" if sev == "high" else "warning"
        cell["status"] = status
        cell["issue"] = {
            "id": f"ISSUE-{iss['issue_id']}",
            "type": itype,
            "title": TYPE_RU.get(itype, itype),
            "severity": sev,
            "plan": f"{iss.get('expected_text') or iss.get('expected') or '—'}",
            "fact": f"{iss.get('actual_text') or iss.get('actual') or '—'}",
            "delta": f"{iss.get('delta') or '—'} ({iss.get('delta_pct', 0):.0f}%)" if pd.notna(iss.get("delta_pct")) else f"{iss.get('delta') or '—'}",
            "impact_som": fmt_som_str(iss.get("impact_som")),
            "explanation": iss.get("explanation") or "",
            "target_jump": target_jump,
        }

    # 2. Аннотируем сопоставления ИИ (🟣 matched-ai)
    for _, ai_r in ai_matches_df.iterrows():
        s_file = ai_r["source_file"]
        s_row = int(ai_r["source_row"])
        doc_id = sanitize_doc_id(s_file)
        if doc_id not in sheets:
            continue

        sheet_obj = sheets[doc_id]
        cols_map = col_mappings.get(s_file, {}).get("columns", {})
        name_col = cols_map.get("work_name_raw", "B")
        if name_col not in sheet_obj["columns"]:
            continue

        for r_entry in sheet_obj["rows"]:
            if r_entry["row_num"] == s_row:
                cell = r_entry["cells"].get(name_col)
                if cell and cell["status"] is None:
                    # Разрешаем ИИ-индикатор только если нет критической ошибки на этой ячейке
                    v_file = ai_r["vor_file"]
                    v_row = int(ai_r["vor_row"])
                    v_doc_id = sanitize_doc_id(v_file)
                    v_col = col_mappings.get(v_file, {}).get("columns", {}).get("work_name_raw", "B")

                    cell["status"] = "ai-matched"
                    cell["ai_match"] = {
                        "confidence": float(ai_r["confidence"]) if pd.notna(ai_r["confidence"]) else 1.0,
                        "reason": ai_r["reason"] or "Семантическое сопоставление наименований работ",
                        "doc_name": ai_r["doc_name"],
                        "vor_name": ai_r["vor_name"],
                        "target_jump": {
                            "doc_id": v_doc_id,
                            "cell": f"{v_col}{v_row}",
                            "title": DOC_TITLES.get(v_file, v_file),
                            "row": v_row,
                            "col": v_col,
                        },
                    }
                break

    # 3. Task 1.3: Агрегация статусов и счетчиков для вкладок
    tabs = []
    first_active_doc = None

    for doc_type, fname, _ in doc_files:
        doc_id = sanitize_doc_id(fname)
        grid = sheets[doc_id]

        red_count = 0
        yellow_count = 0
        ai_count = 0

        for r in grid["rows"]:
            for c in grid["columns"]:
                c_st = r["cells"][c]["status"]
                if c_st == "critical":
                    red_count += 1
                elif c_st == "warning":
                    yellow_count += 1
                elif c_st == "ai-matched":
                    ai_count += 1

        tabs.append({
            "id": doc_id,
            "title": grid["title"],
            "file_name": fname,
            "doc_type": doc_type,
            "red_count": red_count,
            "yellow_count": yellow_count,
            "ai_count": ai_count,
            "total_issues": red_count + yellow_count,
        })

        if first_active_doc is None and red_count > 0:
            first_active_doc = doc_id

    if not first_active_doc and tabs:
        first_active_doc = tabs[0]["id"]

    return {
        "active_doc": first_active_doc or "",
        "tabs": tabs,
        "sheets": sheets,
        "grid": sheets.get(first_active_doc, {"columns": [], "rows": []}),
    }
