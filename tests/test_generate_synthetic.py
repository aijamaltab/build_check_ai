"""Тесты генератора синтетики. Файлы разбираются самостоятельным мини-разборщиком из этого файла
(не кодом приложения): он читает колонки по config/templates.yaml и единицы по config/units.yaml."""
import csv
import hashlib
import importlib.util
import re
from pathlib import Path

import pytest
import yaml
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SEED = 42

spec = importlib.util.spec_from_file_location("generate_synthetic", ROOT / "scripts" / "generate_synthetic.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

TEMPLATES = yaml.safe_load((ROOT / "config" / "templates.yaml").read_text(encoding="utf-8"))["templates"]
UNITS = yaml.safe_load((ROOT / "config" / "units.yaml").read_text(encoding="utf-8"))
RULES = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
NAME_TO_ITEM = gen.all_name_variants()

FILE_TEMPLATE = {"vor_1.xlsx": "vor_a", "vor_2.xlsx": "vor_b", "estimate.xlsx": "estimate_a",
                 "act_1.xlsx": "act_a", "act_2.xlsx": "act_b", "act_3.xlsx": "act_a",
                 "act_4.xlsx": "act_b", "act_5.xlsx": "act_a"}
ACT_FILES = [f"act_{n}.xlsx" for n in range(1, 6)]


# ---------- мини-разборщик ----------
def _clean(s: str) -> str:
    return s.lower().replace(".", "").replace(" ", "")


def parse_unit(text):
    """-> (множитель, каноническая единица). Правила из config/units.yaml."""
    text = str(text).strip()
    factor, rest = 1.0, text
    m = re.match(UNITS["multiplier"]["pattern"], text)
    if m:
        factor = float(m.group(1).replace(",", "."))
        rest = m.group(2)
        assert factor in UNITS["multiplier"]["allowed_factors"], text
    variants = [(_clean(v), canon) for canon, vs in UNITS["units"].items() for v in vs]
    variants += [(_clean(v), canon) for canon, vs in UNITS["noun_units"].items() for v in vs]
    qualifiers = {_clean(q) for q in UNITS["qualifiers"]}
    rest = _clean(rest)
    for v, canon in sorted(variants, key=lambda x: -len(x[0])):
        if rest.startswith(v) and (rest[len(v):] == "" or rest[len(v):] in qualifiers):
            return factor, canon
    raise AssertionError(f"неизвестная единица: {text!r}")


def read_positions(path: Path, template: str):
    """Позиции листа: строки, где есть название, единица и число в «Кол-во»."""
    tpl = TEMPLATES[template]
    ws = load_workbook(path).worksheets[0]
    rows = [[c for c in r] for r in ws.iter_rows(values_only=True)]
    header_idx = next(i for i, r in enumerate(rows)
                      if all(k in " ".join(str(c).lower() for c in r if c is not None) for k in tpl["header_keywords"]))
    header = rows[header_idx]
    col = {}
    for field, names in tpl["columns"].items():
        for i, h in enumerate(header):
            if h is not None and str(h).strip() in names:
                col[field] = i
                break
    patterns = [re.compile(p) for p in tpl.get("skip_row_patterns", [])]
    out, violations = [], []
    for i in range(header_idx + 1, len(rows)):
        r = rows[i]
        text = " ".join(str(c) for c in r if c is not None)
        if not text or any(p.match(text) for p in patterns) or any(k in text.lower() for k in tpl["skip_row_keywords"]):
            continue
        qty, unit, name = r[col["quantity"]], r[col["unit_raw"]], r[col["work_name_raw"]]
        if isinstance(qty, (int, float)) and not (unit and str(unit).strip()):
            violations.append(i + 1)
        if not (isinstance(qty, (int, float)) and unit and name):
            continue
        factor, canon = parse_unit(unit)
        price = r[col["unit_price"]] if "unit_price" in col else None
        out.append({
            "row": i + 1, "name": str(name), "unit": str(unit), "item_no": NAME_TO_ITEM[gen.normalize_name(str(name))],
            "qty": qty, "qty_norm": round(qty * factor, 6), "unit_canon": canon, "factor": factor,
            "price": price, "price_norm": None if price is None else price / factor,
        })
    return out, violations


def read_csv(path: Path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def hash_dir(*dirs):
    out = {}
    for d in dirs:
        for p in sorted(Path(d).rglob("*")):
            if p.is_file():
                out[f"{Path(d).name}/{p.name}"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    base = tmp_path_factory.mktemp("synthetic")
    g = gen.generate(SEED, base / "files", base / "meta")
    data = {}
    for file in FILE_TEMPLATE:
        data[file], _ = read_positions(base / "files" / file, FILE_TEMPLATE[file])
    return {"gen": g, "files": base / "files", "meta": base / "meta", "data": data}


def positions(project, item_no, kind):
    files = [f for f in project["data"] if (f in ACT_FILES) == (kind == "act") and f != "estimate.xlsx"]
    if kind == "estimate":
        files = ["estimate.xlsx"]
    return [(f, p) for f in files for p in project["data"][f] if p["item_no"] == item_no]


def plan_fact(project):
    plan, fact = {}, {}
    for f, rows in project["data"].items():
        for p in rows:
            if f.startswith("vor"):
                plan[p["item_no"]] = plan.get(p["item_no"], 0) + p["qty_norm"]
            elif f in ACT_FILES:
                fact[p["item_no"]] = fact.get(p["item_no"], 0) + p["qty_norm"]
    return plan, fact


# ---------- ground truth ----------
# gt_id -> (файл акта, item_no, количество строки в нормализованных единицах); сверено со спецификацией, раздел 5
GT_ROWS = {1: ("act_3.xlsx", "10", 46), 2: ("act_2.xlsx", "12", 6.4), 3: ("act_2.xlsx", "26", 1760),
           4: ("act_3.xlsx", "21", 690), 5: ("act_3.xlsx", "31", 700), 6: ("act_2.xlsx", "23", 110),
           7: ("act_1.xlsx", "16", 40), 8: ("act_3.xlsx", "37", 120), 9: ("act_3.xlsx", "X1", 150),
           10: ("act_2.xlsx", "X2", 1)}
GT_IMPACT = {1: 101400, 2: 117800, 3: 111600, 4: 109200, 5: 210000, 6: 121000, 7: 28000, 8: 48000,
             9: 195000, 10: 240000}


def test_ground_truth_has_12_rows_with_all_fields(project):
    gt = read_csv(project["meta"] / "ground_truth.csv")
    assert len(gt) == 12
    by_type = {}
    for r in gt:
        by_type[r["issue_type"]] = by_type.get(r["issue_type"], 0) + 1
        for field in ("issue_type", "canonical_name", "source_file", "source_sheet", "source_row", "related_rows",
                      "expected", "actual"):
            assert r[field] != "", (r["gt_id"], field)
    assert by_type == {"volume_exceeded": 5, "price_increase": 3, "missing_in_vor": 2, "late_act": 2}


def test_ground_truth_rows_exist_and_hold_expected_item(project):
    for r in read_csv(project["meta"] / "ground_truth.csv"):
        gid = int(r["gt_id"])
        ws = load_workbook(project["files"] / r["source_file"])[r["source_sheet"]]
        row = int(r["source_row"])
        assert row <= ws.max_row
        if r["issue_type"] == "late_act":
            text = " ".join(str(c.value) for c in ws[row] if c.value is not None)
            act_no = int(re.search(r"\d", r["canonical_name"]).group())
            date = gen.ACTS[act_no][0].strftime("%d.%m.%Y")
            assert f"АКТ № {act_no} от {date}" in text
            assert r["expected"] == "2025-09-30" and r["actual"] == gen.ACTS[act_no][0].isoformat()
            assert r["expected_impact_som"] == ""
            continue
        file, item_no, qty = GT_ROWS[gid]
        assert r["source_file"] == file and r["item_no"] == item_no
        hit = next(p for p in project["data"][file] if p["row"] == row)
        assert hit["item_no"] == item_no
        assert hit["qty_norm"] == pytest.approx(qty)
        assert float(r["expected_impact_som"]) == pytest.approx(GT_IMPACT[gid])


def test_ground_truth_related_rows_point_to_same_item(project):
    for r in read_csv(project["meta"] / "ground_truth.csv"):
        if r["issue_type"] == "late_act":
            assert r["related_rows"] == f"{r['source_file']}:{r['source_sheet']}:{r['source_row']}"
            continue
        refs = [x.split(":") for x in r["related_rows"].split(";")]
        assert f"{r['source_file']}:{r['source_sheet']}:{r['source_row']}" in r["related_rows"].split(";")
        for file, sheet, row in refs:
            hit = next(p for p in project["data"][file] if p["row"] == int(row))
            assert hit["item_no"] == r["item_no"]


def test_price_gt_compares_with_estimate(project):
    by_gt = {int(r["gt_id"]): r for r in read_csv(project["meta"] / "ground_truth.csv")}
    est = {p["item_no"]: p["price_norm"] for p in project["data"]["estimate.xlsx"]}
    for gid in (6, 7, 8):
        assert float(by_gt[gid]["expected"]) == pytest.approx(est[by_gt[gid]["item_no"]])
    assert est["37"] == pytest.approx(1700)   # 170 000 за «100 шт.» в смете


# ---------- ловушки ----------
def test_all_six_traps_are_present(project):
    traps = read_csv(project["meta"] / "traps.csv")
    assert [t["trap_id"] for t in traps] == ["1", "2", "3", "4", "5", "6"]
    for t in traps:
        for ref in t["related_rows"].split(";"):
            file, sheet, row = ref.split(":")
            hit = next(p for p in project["data"][file] if p["row"] == int(row))
            assert hit["item_no"] == t["item_no"]
    plan, fact = plan_fact(project)
    tol_v = RULES["volume_exceeded"]["tolerance_pct"]
    tol_p = RULES["price_increase"]["tolerance_pct"]
    est = {p["item_no"]: p["price_norm"] for p in project["data"]["estimate.xlsx"]}
    act_prices = lambda n: [p["price_norm"] for _, p in positions(project, n, "act")]

    # 1: объём +3%
    assert 0 < (fact["17"] / plan["17"] - 1) * 100 < tol_v
    assert (fact["17"] / plan["17"] - 1) * 100 == pytest.approx(3, abs=0.01)
    # 2: цена +2%
    assert all(0 < (p / est["32"] - 1) * 100 < tol_p for p in act_prices("32"))
    assert act_prices("32")[0] / est["32"] == pytest.approx(1.02)
    # 3: другое написание, одинаковые 60 м3
    vor11 = [p for _, p in positions(project, "11", "vor")]
    act11 = [p["name"] for _, p in positions(project, "11", "act")]
    assert vor11[0]["name"].startswith("Бетон В25") and all(n == "Бетон М350 (перекрытия)" for n in act11)
    assert plan["11"] == fact["11"] == pytest.approx(60)
    # 4: разница в 100 раз до нормализации
    vor6 = positions(project, "6", "vor")[0][1]
    act6 = positions(project, "6", "act")[0][1]
    assert vor6["unit"].startswith("1000") and vor6["qty"] == pytest.approx(0.32)
    assert act6["qty"] == pytest.approx(320) and plan["6"] == fact["6"] == pytest.approx(320)
    # 5: «Строительный мусор» x6, один ключ, суммы равны
    waste_vor = [p for _, p in positions(project, "W1", "vor")]
    assert len(waste_vor) == 6 and len({p["qty"] for p in waste_vor}) == 6
    est_sum = sum(p["qty_norm"] for _, p in positions(project, "W1", "estimate"))
    assert plan["W1"] == pytest.approx(36.1) and est_sum == pytest.approx(36.1) and fact["W1"] == pytest.approx(36.1)
    assert all(p["unit"].startswith("1 т") for p in waste_vor)
    # 6: арматура d8 в пределах плана, d12 не затронута
    assert plan["13"] == pytest.approx(2.2) and abs(fact["13"] / plan["13"] - 1) * 100 < tol_v
    gt2 = next(r for r in read_csv(project["meta"] / "ground_truth.csv") if r["gt_id"] == "2")
    assert float(gt2["actual"]) == pytest.approx(11.4)


# ---------- детерминированность и качество файлов ----------
def test_two_runs_give_identical_hashes(tmp_path):
    gen.generate(SEED, tmp_path / "a" / "files", tmp_path / "a" / "meta")
    gen.generate(SEED, tmp_path / "b" / "files", tmp_path / "b" / "meta")
    ha = hash_dir(tmp_path / "a" / "files", tmp_path / "a" / "meta")
    hb = hash_dir(tmp_path / "b" / "files", tmp_path / "b" / "meta")
    assert ha == hb
    assert len(ha) == 9 + 3   # 9 xlsx и 3 csv


def test_no_position_with_quantity_has_empty_unit(project):
    for file in FILE_TEMPLATE:
        _, violations = read_positions(project["files"] / file, FILE_TEMPLATE[file])
        assert violations == [], (file, violations)


def test_project_size_and_dates(project):
    data = project["data"]
    assert len(data["vor_1.xlsx"]) == 30 and len(data["vor_2.xlsx"]) == 20
    assert len(data["estimate.xlsx"]) == 50
    ws = load_workbook(project["files"] / "contract.xlsx")["Договор"]
    fields = {r[0]: r[1] for r in ws.iter_rows(values_only=True) if r[0]}
    assert fields["Срок выполнения работ до"].date().isoformat() == "2025-09-30"
    assert fields["Цена договора, сом"] == pytest.approx(
        sum(p["qty"] * p["price"] for p in data["estimate.xlsx"] if p["price"]), abs=500)
    for n, (date, _) in gen.ACTS.items():
        assert date.year == 2025 and (date > gen.CONTRACT_DEADLINE) == (n >= 4)


# ---------- ожидаемый светофор ----------
def test_expected_status_matches_files(project):
    rows = read_csv(project["meta"] / "expected_status.csv")
    assert len(rows) == 47
    plan, fact = plan_fact(project)
    tol = RULES["volume_exceeded"]["tolerance_pct"]
    under = RULES["position_status"]["green_under_tolerance_pct"]
    red = {r["item_no"] for r in read_csv(project["meta"] / "ground_truth.csv") if r["issue_type"] != "late_act"}
    counts = {"red": 0, "yellow": 0, "green": 0}
    for r in rows:
        k = r["item_no"]
        assert float(r["fact_qty"]) == pytest.approx(fact.get(k, 0))
        if k in ("X1", "X2"):
            assert r["plan_qty"] == "" and k not in plan
        else:
            assert float(r["plan_qty"]) == pytest.approx(plan[k])
        if k in red:
            expected = "red"
        else:
            pct = fact.get(k, 0) / plan[k] * 100
            expected = "green" if 100 - under <= pct <= 100 + tol else "yellow"
            assert pct <= 100 + tol
        assert r["expected_status"] == expected, k
        counts[expected] += 1
    assert counts == {"red": 10, "yellow": 6, "green": 31}
    assert {r["item_no"] for r in rows if r["expected_status"] == "yellow"} == {"28", "30", "33", "34", "35", "38"}
