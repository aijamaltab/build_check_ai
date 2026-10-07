"""Тесты для интерактивного экрана аудита документов (Google Sheets Lookalike, new_feat.md).

Task 4.1: Тесты на корректность координат ячеек и target_jump
Task 4.2: Проверка производительности формирования модели
Task 4.3: Корректность работы без ИИ (rules_only)
"""
import tempfile
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.pipeline import run_pipeline
from ui.sheet_builder import (
    build_sheet_audit_model,
    detect_doc_columns,
    extract_sheet_grid,
    sanitize_doc_id,
)
from ui.sheets_view import sheets_html

ROOT = Path(__file__).resolve().parents[1]
SYNTH_DIR = ROOT / "data" / "synthetic"


@pytest.fixture(scope="module")
def demo_dbs(tmp_path_factory):
    """Строим базы llm и rules_only один раз для тестов."""
    tdir = tmp_path_factory.mktemp("sheets_audit_test")
    db_llm = tdir / "demo_llm.db"
    db_rules = tdir / "demo_rules_only.db"

    run_pipeline(SYNTH_DIR, db_llm, mode="llm")
    run_pipeline(SYNTH_DIR, db_rules, mode="rules_only")

    return {"llm": db_llm, "rules_only": db_rules}


def test_extract_sheet_grid_boundaries():
    """Task 1.1 / 4.1: Проверка извлечения сетки openpyxl и границ bounding box."""
    act1_path = SYNTH_DIR / "act_1.xlsx"
    grid = extract_sheet_grid(act1_path)

    assert grid["max_row"] == 34
    assert grid["max_col"] == 7
    assert grid["columns"] == ["A", "B", "C", "D", "E", "F", "G"]
    assert len(grid["rows"]) == 34

    # Проверяем строку 6 (шапка акта)
    r6 = next(r for r in grid["rows"] if r["row_num"] == 6)
    assert "Наименование" in r6["cells"]["B"]["value"]
    assert "Выполнено" in r6["cells"]["D"]["value"]


def test_detect_doc_columns_maps_fields_correctly():
    """Task 1.1 / 4.1: Корректное сопоставление полей шаблонов с буквами колонок."""
    from src.config import load_config
    cfg = load_config()

    grid_act1 = extract_sheet_grid(SYNTH_DIR / "act_1.xlsx")
    col_map_act1 = detect_doc_columns(grid_act1, cfg["templates"])
    assert col_map_act1["template"] == "act_a"
    assert col_map_act1["columns"]["quantity"] == "D"
    assert col_map_act1["columns"]["unit_price"] == "E"

    grid_act2 = extract_sheet_grid(SYNTH_DIR / "act_2.xlsx")
    col_map_act2 = detect_doc_columns(grid_act2, cfg["templates"])
    assert col_map_act2["template"] == "act_b"
    assert col_map_act2["columns"]["quantity"] == "C"
    assert col_map_act2["columns"]["unit_raw"] == "D"


def test_coordinates_match_issues_strictly(demo_dbs):
    """Task 4.1: Координаты подсвеченных ячеек строго совпадают с source_row и связаны с целевыми документами."""
    model = build_sheet_audit_model(SYNTH_DIR, demo_dbs["llm"])

    # 1. Проверяем превышение объема в act_3 строка 19 -> прыжок в vor_1 строка 46 колонка D
    act3_sheet = model["sheets"]["act_3"]
    r19 = next(r for r in act3_sheet["rows"] if r["row_num"] == 19)
    cell_d19 = r19["cells"]["D"]
    assert cell_d19["status"] == "critical"
    assert cell_d19["issue"]["type"] == "volume_exceeded"
    jump = cell_d19["issue"]["target_jump"]
    assert jump["doc_id"] == "vor_1"
    assert jump["cell"] == "D46"
    assert jump["row"] == 46
    assert jump["col"] == "D"

    # Обратная связь в vor_1
    vor1_sheet = model["sheets"]["vor_1"]
    r46 = next(r for r in vor1_sheet["rows"] if r["row_num"] == 46)
    cell_d46 = r46["cells"]["D"]
    assert cell_d46["status"] == "critical"
    assert cell_d46["issue"]["target_jump"]["doc_id"] == "act_3"

    # 2. Проверяем рост цены в act_2 строка 24 -> прыжок в estimate строка 42 колонка F
    act2_sheet = model["sheets"]["act_2"]
    r24 = next(r for r in act2_sheet["rows"] if r["row_num"] == 24)
    cell_e24 = r24["cells"]["E"]
    assert cell_e24["status"] == "critical"
    assert cell_e24["issue"]["type"] == "price_increase"
    jump_price = cell_e24["issue"]["target_jump"]
    assert jump_price["doc_id"] == "estimate"
    assert jump_price["cell"] == "F42"

    # 3. Проверяем late_act в act_4 строка 2 -> прыжок в contract строка 6 колонка B
    act4_sheet = model["sheets"]["act_4"]
    r2 = next(r for r in act4_sheet["rows"] if r["row_num"] == 2)
    # В заголовке акта подсвечивается дата
    cell_date = r2["cells"]["A"]
    assert cell_date["status"] in ("critical", "warning")
    assert cell_date["issue"]["type"] == "late_act"
    jump_late = cell_date["issue"]["target_jump"]
    assert jump_late["doc_id"] == "contract"
    assert jump_late["cell"] == "B6"


def test_ai_matched_cells_have_purple_status_and_confidence(demo_dbs):
    """Task 1.2 / 2.2: Сопоставления ИИ имеют статус ai-matched и содержат обоснование."""
    model = build_sheet_audit_model(SYNTH_DIR, demo_dbs["llm"])

    act2_sheet = model["sheets"]["act_2"]
    ai_cells = []
    for r in act2_sheet["rows"]:
        for col, cell in r["cells"].items():
            if cell["status"] == "ai-matched":
                ai_cells.append(cell)

    assert len(ai_cells) > 0
    first_ai = ai_cells[0]
    assert first_ai["ai_match"] is not None
    assert first_ai["ai_match"]["confidence"] >= 0.85
    assert len(first_ai["ai_match"]["reason"]) > 5
    assert first_ai["ai_match"]["target_jump"]["doc_id"].startswith("vor")


def test_tab_counts_aggregate_correctly(demo_dbs):
    """Task 1.3: Счётчики рисков на вкладках корректно агрегируют 🔴/🟡/🟣."""
    model = build_sheet_audit_model(SYNTH_DIR, demo_dbs["llm"])
    tabs = {t["id"]: t for t in model["tabs"]}

    assert len(tabs) == 9
    assert tabs["act_2"]["red_count"] == 3
    assert tabs["act_2"]["yellow_count"] >= 1
    assert tabs["act_2"]["ai_count"] >= 10
    assert tabs["act_3"]["red_count"] == 3


def test_performance_model_building_and_html_generation(demo_dbs):
    """Task 4.2: Формирование модели на 9 документов укладывается в доли секунды."""
    t0 = time.perf_counter()
    model = build_sheet_audit_model(SYNTH_DIR, demo_dbs["llm"])
    t1 = time.perf_counter()
    html_content = sheets_html(model)
    t2 = time.perf_counter()

    build_time = t1 - t0
    render_time = t2 - t1

    assert build_time < 1.0, f"Model build took {build_time:.3f}s (expected < 1.0s)"
    assert render_time < 0.2, f"HTML render took {render_time:.3f}s (expected < 0.2s)"
    assert "const DATA =" in html_content
    assert "popover-card" in html_content


def test_rules_only_mode_works_without_ai(demo_dbs):
    """Task 4.3: Корректность работы без ИИ (rules_only)."""
    model = build_sheet_audit_model(SYNTH_DIR, demo_dbs["rules_only"])

    assert len(model["tabs"]) == 9
    # В режиме без ИИ нет сопоставлений ИИ
    total_ai = sum(t["ai_count"] for t in model["tabs"])
    assert total_ai == 0

    # Но все базовые расхождения 🔴 и вкладки присутствуют
    assert model["sheets"]["act_2"] is not None
    html_content = sheets_html(model)
    assert len(html_content) > 10000


def test_streamlit_sheets_view_renders_apptest():
    """Проверка рендеринга страницы Streamlit через AppTest."""
    def run_sheets():
        import tempfile
        from pathlib import Path
        from src.pipeline import run_pipeline
        from ui.sheet_builder import build_sheet_audit_model
        from ui.sheets_view import render_sheets_view

        root = Path(__file__).resolve().parents[1]
        synth_dir = root / "data" / "synthetic"
        tdir = Path(tempfile.gettempdir()) / "test_apptest_sheets"
        tdir.mkdir(exist_ok=True)
        db_path = tdir / "test.db"
        if not db_path.exists():
            run_pipeline(synth_dir, db_path, mode="rules_only")
        model = build_sheet_audit_model(synth_dir, db_path)
        render_sheets_view(model)

    at = AppTest.from_function(run_sheets, default_timeout=180).run()
    assert not at.exception
    assert len(at.get("iframe")) == 1
