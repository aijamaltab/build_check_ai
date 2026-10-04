"""Ingestion на синтетике: сверка с журналом генератора (он знает, какие строки и значения записал).

Синтетика генерируется во временную папку; файлы в data/ не трогаем.
"""
import pytest

from src.config import load_config
from src.ingestion.items import build_items
from src.ingestion.parse import parse_workbook
from tests.test_generate_synthetic import gen

CFG = load_config()
TOL = 1e-6


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    g = gen.generate(out_dir=out, meta_dir=out)
    return out, g


@pytest.fixture(scope="module")
def parsed(synth):
    """файл -> (ParsedDoc, [ItemDraft])"""
    out, _ = synth
    result = {}
    for path in sorted(out.glob("*.xlsx")):
        doc = parse_workbook(path, path.name, CFG)
        result[path.name] = (doc, build_items(doc, CFG))
    return result


def log_of(synth, file):
    return {r["row"]: r for r in synth[1].log if r["file"] == file}


def check_file_against_log(synth, parsed, file):
    """Те же строки (лист, номер), то же количество после нормализации, цена и сумма."""
    doc, items = parsed[file]
    log = log_of(synth, file)
    assert doc.unrecognized == [] and doc.errors == []
    assert {i.source_row for i in items} == set(log), "наборы строк различаются"
    for it in items:
        ref = log[it.source_row]
        assert doc.sheet == ref["sheet"]
        assert it.quantity == pytest.approx(ref["qty_norm"], abs=TOL), (file, it.source_row, it.work_name_raw)
        if ref["price_norm"] is None:
            assert it.unit_price is None, (file, it.source_row)
        else:
            assert it.unit_price == pytest.approx(ref["price_norm"], abs=TOL), (file, it.source_row)
        if ref["amount"] is not None:
            assert it.amount == pytest.approx(ref["amount"], abs=0.005)


# ---------- ВОР ----------
@pytest.mark.parametrize("file,template,count", [("vor_1.xlsx", "vor_a", 30), ("vor_2.xlsx", "vor_b", 20)])
def test_vor_rows_match_generator(synth, parsed, file, template, count):
    doc, items = parsed[file]
    assert doc.template == template and doc.doc_type == "vor"
    assert len(items) == count
    check_file_against_log(synth, parsed, file)


def test_vor_has_no_prices_and_no_dates(parsed):
    for file in ("vor_1.xlsx", "vor_2.xlsx"):
        _, items = parsed[file]
        assert all(i.unit_price is None and i.amount is None and i.doc_date is None for i in items)


def test_vor_service_rows_never_become_items(parsed):
    names = [i.work_name_raw.lower() for f in ("vor_1.xlsx", "vor_2.xlsx") for i in parsed[f][1]]
    assert not any(n.startswith(("раздел", "итого", "всего", "составил", "основания")) for n in names)
    assert not any(n.isdigit() for n in names)


def test_vor2_multipliers_and_materials(parsed):
    """Кабель 24 «100 м» -> 2400 м, светильники 2,1 «100 шт.» -> 210, радиаторы 4,8 «10 шт.» -> 48, трубы 6,5 «100 м» -> 650."""
    items = parsed["vor_2.xlsx"][1]
    works = {36: ("кабель", 24, 2400, "m"), 37: ("светильники led монтаж", 2.1, 210, "pcs"),
             39: ("установка радиаторов", 4.8, 48, "pcs"), 40: ("прокладка трубопроводов", 6.5, 650, "m")}
    for _, (prefix, raw, norm, unit) in works.items():
        it = next(i for i in items if i.kind_hint == "work" and i.name_norm.startswith(prefix))
        assert (float(it.quantity_raw), it.quantity, it.unit_norm) == (raw, norm, unit)
    materials = {i.name_norm: i for i in items if i.kind_hint == "material"}
    assert len(materials) == 4
    assert {k.split()[0]: (v.quantity, v.unit_norm) for k, v in materials.items()} == {
        "кабель": (2400, "m"), "светильники": (210, "pcs"), "радиаторы": (48, "pcs"), "трубы": (650, "m")}
    # материал и работа это разные строки с разным kind, в сумму не сливаются
    cable = [i for i in items if i.name_norm.startswith("кабель")]
    assert sorted(i.kind_hint for i in cable) == ["material", "work"]
    assert len({i.work_key for i in cable}) == 2


def test_vor2_waste_rows_are_kept_separately(parsed):
    waste = [i for i in parsed["vor_2.xlsx"][1] if i.name_norm == "строительный мусор"]
    assert [i.quantity for i in waste] == [12.5, 8, 3.2, 4.4, 2, 6]
    assert sum(i.quantity for i in waste) == pytest.approx(36.1)
    assert {i.work_key for i in waste} == {"work:строительный мусор|t"}      # один ключ, но не суммируем


def test_vor_markers_and_names(parsed):
    items = parsed["vor_1.xlsx"][1] + parsed["vor_2.xlsx"][1]
    assert not any("/прим/" in i.name_norm for i in items)
    assert any("/прим/" in i.work_name_raw for i in items)              # исходное название сохранено
    assert all(i.kind_hint == "work" for i in parsed["vor_1.xlsx"][1])


# ---------- смета и договор ----------
def test_estimate_rows_prices_and_total(synth, parsed):
    doc, items = parsed["estimate.xlsx"]
    assert doc.template == "estimate_a" and doc.doc_type == "estimate" and len(items) == 50
    check_file_against_log(synth, parsed, "estimate.xlsx")
    # цена за единицу нормы делится на множитель: «100 шт.» 170 000 -> 1 700 за штуку
    lamp = next(i for i in items if i.name_norm == "установка светодиодных светильников")
    assert (lamp.quantity, lamp.unit_price, lamp.unit_norm) == (210, 1700, "pcs")
    # итог «Итого по смете» это не позиция: он нужен только для dq «сумма строк = итог»
    assert doc.total_amount == pytest.approx(sum(i.amount for i in items if i.amount), abs=0.01)
    assert not any(i.name_norm.startswith("итого") for i in items)


def test_contract_is_one_item_with_deadline_and_total(parsed):
    doc, items = parsed["contract.xlsx"]
    assert doc.doc_type == "contract" and len(items) == 1
    c = items[0]
    assert (c.work_name_raw, c.doc_date, c.amount) == ("Договор", "2025-09-30", 13954000)
    assert c.source_row == 6 and c.quantity is None and c.unit_price is None


# ---------- акты ----------
@pytest.mark.parametrize("n,template,count,date", [(1, "act_a", 24, "2025-05-31"), (2, "act_b", 28, "2025-06-30"),
                                                   (3, "act_a", 24, "2025-08-31"), (4, "act_b", 2, "2025-10-17"),
                                                   (5, "act_a", 2, "2025-11-14")])
def test_acts_match_generator(synth, parsed, n, template, count, date):
    file = f"act_{n}.xlsx"
    doc, items = parsed[file]
    assert doc.template == template and doc.doc_type == "act" and len(items) == count
    assert {i.doc_date for i in items} == {date} and doc.date_row == synth[1].act_title_row[n]
    check_file_against_log(synth, parsed, file)


def test_act_total_row_is_not_an_item_and_equals_sum(parsed):
    doc, items = parsed["act_2.xlsx"]
    assert doc.total_amount == 6485749.6
    assert sum(i.amount for i in items if i.amount) == pytest.approx(6485749.6, abs=0.01)
    assert not any("итого" in i.name_norm for i in items)


def test_act_b_unit_with_multiplier(parsed):
    """Акт №2 пишет штукатурку стен в «100 м2»: 17,6 -> 1 760 м2, цена 31 000 -> 310."""
    it = next(i for i in parsed["act_2.xlsx"][1] if i.name_norm == "штукатурка стен ц/п раствором")
    assert (it.unit_raw, it.quantity_raw, it.quantity, it.unit_price, it.unit_norm) == ("100 м2", "17.6", 1760, 310, "m2")
