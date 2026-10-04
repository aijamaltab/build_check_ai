"""Тесты нормализации: единицы, множители, названия, числа, даты."""
import datetime as dt

import pytest

from src.config import load_config
from src.normalize import UnitNormalizer, find_date_in_text, normalize_name, parse_date, parse_number

CFG = load_config()
UN = UnitNormalizer(CFG["units"])


@pytest.mark.parametrize("text", ["м3", "куб.м", "м³", "Куб. м"])
def test_volume_spellings(text):
    r = UN.parse(text)
    assert (r.ok, r.unit_norm, r.factor) == (True, "m3", 1.0)


@pytest.mark.parametrize("text,unit,factor", [
    ("100 м2", "m2", 100), ("1000 м3", "m3", 1000), ("100 шт.", "pcs", 100), ("10 шт.", "pcs", 10),
    ("1 т груза", "t", 1), ("100 м трубопровода", "m", 100), ("100 м3 бетона в деле", "m3", 100),
    ("100 м2 окрашиваемой поверхности", "m2", 100), ("100 м", "m", 100), ("100м2", "m2", 100),
])
def test_norm_multipliers(text, unit, factor):
    r = UN.parse(text)
    assert r.ok and r.unit_norm == unit and r.factor == factor


@pytest.mark.parametrize("text,unit", [("м.п.", "m"), ("пог.м", "m"), ("тн", "t"), ("тонн", "t"),
                                       ("штук", "pcs"), ("компл.", "set"), ("кв.м", "m2")])
def test_other_spellings(text, unit):
    assert UN.parse(text).unit_norm == unit


def test_noun_units_are_pieces_and_flagged():
    for text in ("светильник", "радиатор"):
        r = UN.parse(text)
        assert (r.ok, r.unit_norm, r.is_noun) == (True, "pcs", True)
    r = UN.parse("100 коробок")
    assert (r.unit_norm, r.factor, r.is_noun) == ("pcs", 100, True)
    assert not UN.parse("шт").is_noun


@pytest.mark.parametrize("text", ["", None, "парсек", "5 м", "100", "м2 чего-то"])
def test_unknown_units(text):
    assert not UN.parse(text).ok


def test_name_normalization_keeps_brackets():
    markers = CFG["synonyms"]["strip_markers"]
    assert normalize_name("  Окраска   Стен /прим/ ", markers) == "окраска стен"
    assert normalize_name("Шпаклёвка стен (ЦПР)", markers) == "шпаклевка стен (цпр)"


def test_numbers_comma_and_dot():
    assert parse_number("12,5") == 12.5
    assert parse_number("12.5") == 12.5
    assert parse_number(" 1 200,5") == 1200.5
    assert parse_number(7) == 7.0
    for bad in (None, "", "по смете: 0,146", "6 м / 100 = 0,06", True):
        assert parse_number(bad) is None


def test_dates():
    assert parse_date(dt.datetime(2025, 9, 30)) == dt.date(2025, 9, 30)
    assert parse_date("30.09.2025") == dt.date(2025, 9, 30)
    assert parse_date("2025-09-30") == dt.date(2025, 9, 30)
    assert parse_date("31.02.2025") is None and parse_date("вчера") is None
    regex = CFG["templates"]["act_a"]["doc_date_regex"]
    assert find_date_in_text("АКТ № 2 от 30.06.2025 о приёмке", regex) == dt.date(2025, 6, 30)
