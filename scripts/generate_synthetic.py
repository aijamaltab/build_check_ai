#!/usr/bin/env python
"""Генератор синтетического демо-проекта «капремонт школы» по docs/synthetic_spec.md.

Пишет в data/synthetic: vor_1.xlsx, vor_2.xlsx, estimate.xlsx, contract.xlsx, act_1..act_5.xlsx
и в data/: ground_truth.csv, traps.csv, expected_status.csv.

Все 40 позиций лежат одной таблицей ITEMS_RAW, файлы собираются из неё. Ошибки (заложенные расхождения)
вносятся при построении строк актов, а ground_truth.csv берёт лист и номер строки из реально
записанных листов (журнал строк self.log), а не вычисляет их отдельно.

Данные синтетические: объект, организации и подписи выдуманные, цены ориентировочные, не рыночные.
Без сети. Один и тот же seed даёт побайтно одинаковые файлы.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import random
import re
import sys
import zipfile
from collections import namedtuple
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEED = 42
FIXED_DT = dt.datetime(2025, 1, 1, 0, 0, 0)

CONTRACT_START = dt.date(2025, 3, 1)
CONTRACT_DEADLINE = dt.date(2025, 9, 30)
APPROVE_DATE = "20.02.2025"
# номер акта -> (дата, шаблон)
ACTS = {
    1: (dt.date(2025, 5, 31), "a"),
    2: (dt.date(2025, 6, 30), "b"),
    3: (dt.date(2025, 8, 31), "a"),
    4: (dt.date(2025, 10, 17), "b"),
    5: (dt.date(2025, 11, 14), "a"),
}

Item = namedtuple("Item", "no section unit qty price name_a name_b name_c")

# Все 40 видов работ. qty и price в нормализованных единицах (м2, м3, шт...), цены в сомах, ориентировочные.
# no, раздел, единица, объём, цена, вариант А (ВОР-1, смета), вариант Б (ВОР-2), вариант В (акты)
ITEMS_RAW = [
    (1, "demol", "m3", 45, 1800, "Демонтаж кирпичных перегородок", "Разборка перегородок из кирпича", "Демонтаж перегородок кирп."),
    (2, "demol", "m2", 1200, 120, "Демонтаж кровельного покрытия из шифера", "Разборка шиферной кровли", "Демонтаж шифера с кровли"),
    (3, "demol", "m2", 180, 150, "Демонтаж оконных блоков", "Разборка окон", "Демонтаж окон. блоков"),
    (4, "demol", "pcs", 24, 250, "Демонтаж дверных блоков", "Разборка дверей", "Демонтаж дверн. блоков"),
    (5, "demol", "m2", 900, 110, "Разборка покрытий полов", "Демонтаж напольных покрытий", "Разборка пола"),
    (6, "earth", "m3", 320, 450, "Разработка грунта экскаватором", "Выемка грунта механизированная", "Разр. грунта экскаватором"),
    (7, "earth", "m3", 60, 900, "Разработка грунта вручную", "Ручная выемка грунта", "Копка грунта вручную"),
    (8, "earth", "m3", 40, 1400, "Устройство песчаной подготовки", "Песчаное основание под фундамент", "Подготовка из песка"),
    (9, "earth", "m3", 25, 5200, "Устройство бетонной подготовки", "Бетонная подготовка В7,5", "Подготовка бетонная"),
    (10, "conc", "m3", 85, 7800, "Бетон М300 для фундаментов", "Бетонная смесь М-300", "Бетон тяж. кл. В22,5"),
    (11, "conc", "m3", 60, 8400, "Бетон В25 для плит перекрытий", "Бетон М350 (перекрытия)", "Бетонирование плит перекр. В25"),
    (12, "conc", "t", 9.5, 62000, "Арматура А500 d12", "Арматурная сталь А-500С ф12", "Арм. А500 Ø12"),
    (13, "conc", "t", 2.2, 58000, "Арматура А240 d8", "Арматурная сталь А-I ф8", "Арматура гладкая Ø8"),
    (14, "conc", "m2", 420, 650, "Установка опалубки", "Опалубка щитовая", "Устройство и разборка опалубки"),
    (15, "conc", "m2", 350, 380, "Обмазочная гидроизоляция фундаментов", "Гидроизоляция фундамента битумная", "Гидроизол. обмазочная"),
    (16, "mason", "m3", 120, 6200, "Кладка кирпичных стен", "Кирпичная кладка наружных стен", "Кладка стен из кирпича"),
    (17, "mason", "m3", 70, 4800, "Кладка перегородок из газоблока", "Перегородки газобетонные", "Устройство перегородок из газоблоков"),
    (18, "mason", "pcs", 60, 1100, "Устройство перемычек", "Монтаж ж/б перемычек", "Перемычки сборные"),
    (19, "roof", "m2", 1100, 720, "Утепление стен минераловатными плитами", "Теплоизоляция фасада минвата", "Утепл. стен минватой"),
    (20, "roof", "m3", 28, 14500, "Устройство стропильной системы", "Монтаж деревянных стропил", "Стропильная система кровли"),
    (21, "roof", "m2", 1250, 780, "Кровля из профнастила", "Покрытие кровли профлистом", "Устройство кровли профнастил"),
    (22, "roof", "m", 180, 520, "Монтаж водосточной системы", "Водосточные желоба и трубы", "Водосток (монтаж)"),
    (23, "win", "m2", 190, 6800, "Установка окон ПВХ двухкамерных", "Окна из ПВХ профиля", "Монтаж оконных блоков ПВХ"),
    (24, "win", "pcs", 6, 14000, "Установка металлических дверей", "Двери стальные", "Монтаж дверей металл."),
    (25, "win", "pcs", 22, 7500, "Установка деревянных дверей", "Двери деревянные внутренние", "Монтаж дверных блоков (дерево)"),
    (26, "fin", "m2", 3200, 310, "Штукатурка стен цементно-песчаная", "Оштукатуривание стен ЦПР", "Штукатурка стен ц/п раствором"),
    (27, "fin", "m2", 3200, 180, "Шпаклёвка стен", "Шпатлёвка поверхностей стен", "Шпаклевание стен"),
    (28, "fin", "m2", 260, 350, "Штукатурка оконных откосов", "Отделка откосов", "Откосы окон штукатурка"),
    (29, "fin", "m2", 3200, 140, "Окраска стен водоэмульсионная", "Покраска стен ВД краской", "Окраска стен в/э составом"),
    (30, "fin", "m2", 1400, 130, "Окраска потолков", "Покраска потолков", "Окраска потолков водоэмульс."),
    (31, "fin", "m2", 1500, 420, "Устройство цементной стяжки пола", "Стяжка пола ЦПС", "Стяжка цем.-песч."),
    (32, "fin", "m2", 700, 1050, "Укладка керамогранита", "Покрытие пола керамогранит", "Облицовка пола керамогранитом"),
    (33, "fin", "m2", 800, 480, "Укладка линолеума", "Покрытие пола линолеум", "Устройство покрытия из линолеума"),
    (34, "fin", "m2", 320, 980, "Облицовка стен плиткой (санузлы)", "Кафельная облицовка стен", "Обл. стен керамической плиткой"),
    (35, "fin", "m2", 600, 750, "Монтаж подвесных потолков типа Армстронг", "Потолки подвесные кассетные", "Подвесной потолок Armstrong"),
    (36, "elec", "m", 2400, 95, "Прокладка кабеля ВВГнг 3×2,5", "Кабель ВВГ-нг 3х2.5 прокладка", "Прокладка кабеля ВВГ 3*2,5"),
    (37, "elec", "pcs", 210, 1700, "Установка светодиодных светильников", "Светильники LED монтаж", "Монтаж светильников светодиод."),
    (38, "elec", "pcs", 160, 320, "Установка розеток и выключателей", "Монтаж электроустановочных изделий", "Розетки, выключатели (установка)"),
    (39, "heat", "pcs", 48, 5400, "Монтаж радиаторов отопления биметаллических", "Установка радиаторов биметалл", "Радиаторы отопления (монтаж)"),
    (40, "heat", "m", 650, 420, "Прокладка труб отопления полипропиленовых", "Трубопровод отопления из ППР", "Монтаж труб отопления PPR"),
]
ITEMS = [Item(*row) for row in ITEMS_RAW]
BY_NO = {it.no: it for it in ITEMS}

# Единицы с множителем нормы (в ВОР и смете): номер -> (множитель, текст единицы)
NORM = {
    2: (100, "100 м2"),
    3: (100, "100 м2"),
    6: (1000, "1000 м3"),
    10: (100, "100 м3 бетона в деле"),
    21: (100, "100 м2"),
    29: (100, "100 м2 окрашиваемой поверхности"),
    36: (100, "100 м"),
    37: (100, "100 шт."),
    39: (10, "10 шт."),
    40: (100, "100 м трубопровода"),
}

# Длинные нормативные названия в ВОР (в смете и актах названия короткие)
LONG_NAMES = {
    5: "Разборка покрытий полов: из линолеума и поливинилхлоридных плиток",
    8: "Устройство подстилающих и выравнивающих слоёв оснований: песчаных",
    15: "Гидроизоляция стен и фундаментов: обмазочная битумная двухслойная",
    19: "Утепление наружных стен плитами минераловатными толщиной 100 мм с креплением тарельчатыми дюбелями",
    20: "Устройство стропильной системы кровли из деревянных брусьев с антисептированием",
    28: "Штукатурка оконных и дверных откосов цементно-песчаным раствором по камню",
    30: "Окраска потолков водоэмульсионными составами по подготовленной поверхности",
    34: "Облицовка стен глазурованными керамическими плитками на клее в санузлах",
    35: "Монтаж подвесных потолков типа Армстронг по каркасу из оцинкованного профиля",
    40: "Прокладка трубопроводов отопления из полипропиленовых труб диаметром до 32 мм",
}

WASTE_NAME = "Строительный мусор"
WASTE_QTY = [12.5, 8, 3.2, 4.4, 2, 6]
WASTE_PARENT = [1, 2, 3, 4, 5, 40]   # мусор стоит после работы с этим номером
WASTE_ACT = [1, 1, 1, 1, 1, 3]       # в каком акте выполнена соответствующая строка мусора

# Материалы отдельными строками после работы: номер работы -> (название А/Б, название В, единица)
MATERIALS = {
    36: ("Кабель ВВГнг 3×2,5", "Кабель ВВГ-нг 3х2,5", "м"),
    37: ("Светильники LED", "Светильники светодиодные", "светильник"),
    39: ("Радиаторы биметаллические", "Радиаторы биметаллические секционные", "радиатор"),
    40: ("Трубы ППР", "Трубы полипропиленовые ППР", "м"),
}

# Позиции без ВОР (GT-9, GT-10): номер, название, единица, количество, цена, акт, тег
EXTRAS = {
    "X1": ("Устройство отмостки вокруг здания", "m2", 150, 1300, 3, "GT9"),
    "X2": ("Монтаж системы видеонаблюдения", "set", 1, 240000, 2, "GT10"),
}

UNIT_SPELL = {
    "m3": ["м3", "куб.м", "м³"],
    "m2": ["м2", "кв.м", "м²"],
    "m": ["м.п.", "пог.м", "м"],
    "pcs": ["шт", "шт.", "штук"],
    "t": ["т", "тн", "тонн"],
    "set": ["компл."],
}

SECTION_ORDER = ["demol", "earth", "conc", "mason", "roof", "win", "fin", "elec", "heat"]
SECTION_TITLE = {
    "demol": "Демонтажные работы",
    "earth": "Земляные работы",
    "conc": "Бетонные и железобетонные работы",
    "mason": "Каменные работы",
    "roof": "Утепление и кровля",
    "win": "Окна и двери",
    "fin": "Отделочные работы",
    "elec": "Электроснабжение и освещение",
    "heat": "Отопление",
}
VOR1_SECTIONS = ["earth", "conc", "mason", "roof", "win", "fin"]
VOR2_SECTIONS = ["demol", "elec", "heat"]
DRAWING_REF = {"demol": "АР-1", "elec": "ЭО-2", "heat": "ОВ-1"}

# Акты, в которых выполняется раздел (если у позиции нет особого сценария)
DEFAULT_ACTS = {
    "demol": (1,), "earth": (1, 2), "conc": (1, 2), "mason": (1, 2), "roof": (2, 3),
    "win": (2, 3), "fin": (2, 3), "elec": (3,), "heat": (3,),
}

# Особые сценарии: номер -> строки акта (акт, количество в обычных единицах, цена или None = цена сметы).
# Суммы подобраны по docs/synthetic_spec.md (разделы 5 и 9).
FIXED_ROWS = {
    6: [(1, 320, None)],                              # ловушка 4: ВОР «1000 м3» x 0,32, акт 320 м3
    10: [(2, 52, None), (3, 46, None)],               # GT-1: 98 против 85
    11: [(1, 30, None), (2, 30, None)],               # ловушка 3: 60 м3, название в акте вариантом Б
    12: [(1, 5.0, None), (2, 6.4, None)],             # GT-2: 11,4 против 9,5
    13: [(1, 1.0, None), (2, 1.2, None)],             # ловушка 6: d8 в пределах плана
    16: [(1, 40, 6900), (2, 78, None)],               # GT-7: цена в акте №1 6 900
    17: [(1, 28.8, None), (2, 43.3, None)],           # ловушка 1: 72,1 против 70 (+3%)
    21: [(2, 700, None), (3, 690, None)],             # GT-4: 1 390 против 1 250
    23: [(2, 110, 7900), (3, 80, None)],              # GT-6: цена в акте №2 7 900
    26: [(1, 1800, None), (2, 1760, None)],           # GT-3: 3 560 против 3 200 (акт №2 в «100 м2»)
    28: [(4, 130, None)],                             # жёлтая, акт №4
    30: [(4, 700, None)],                             # жёлтая, акт №4
    31: [(1, 600, None), (2, 700, None), (3, 700, None)],   # GT-5: дубль строки в актах №2 и №3
    33: [(3, 440, None)],                             # жёлтая, 55%
    34: [(5, 150, None)],                             # жёлтая, акт №5
    35: [(2, 210, None), (3, 210, None)],             # жёлтая, 70%
    37: [(2, 90, None), (3, 120, 2100)],              # GT-8: цена в акте №3 2 100 (смета 1 700)
    38: [(5, 80, None)],                              # жёлтая, акт №5
}
PRICE_ALL = {32: 1071}                                # ловушка 2: цена +2% во всех строках №32
NAME_VARIANT_ACT = {11: "b"}                          # ловушка 3: в акте вариант Б
ACT_NORM = {(26, 2): (100, "100 м2")}                 # акт №2 пишет штукатурку в «100 м2»
FORCE_UNIT = {(31, 2): "м2", (31, 3): "м2"}           # строки-дубли совпадают полностью
ROW_TAG = {(23, 2): "GT6", (16, 1): "GT7", (37, 3): "GT8", (31, 3): "GT5"}

VOLUME_GT = [(1, 10), (2, 12), (3, 26), (4, 21), (5, 31)]
PRICE_GT = [("GT6", 6, 23), ("GT7", 7, 16), ("GT8", 8, 37)]
MISSING_GT = [("GT9", 9, "X1"), ("GT10", 10, "X2")]

TRAPS = [
    (1, "17", "Объём +3% (72,1 против 70 м3): ниже допуска, расхождения быть не должно"),
    (2, "32", "Цена +2% (1 071 против 1 050): ниже допуска, расхождения быть не должно"),
    (3, "11", "Другое написание: в ВОР «Бетон В25», в акте «Бетон М350 (перекрытия)», по 60 м3"),
    (4, "6", "Разница в 100 раз до нормализации: ВОР «1000 м3» x 0,32, акт 320 м3"),
    (5, "W1", "«Строительный мусор» x6: один ключ, не дубли, суммы 36,1 т равны в ВОР, смете и актах"),
    (6, "13", "Арматура А240 d8 рядом с А500 d12: по №13 расхождения быть не должно, объём GT-2 не меняется"),
]

GT_COLUMNS = ["gt_id", "issue_type", "scenario", "item_no", "canonical_name", "source_file", "source_sheet",
              "source_row", "related_rows", "expected", "actual", "expected_impact_som"]

NOTES = ["см. черт. АС-3", "уточнить по месту", "по дефектной ведомости", "согласовано", "см. спецификацию"]


def fmt(x) -> str:
    """Число в CSV: без хвоста нулей."""
    return ("%.6f" % x).rstrip("0").rstrip(".")


def num(x):
    """Число в ячейку: целое остаётся целым."""
    x = round(float(x), 6)
    return int(x) if x.is_integer() else x


def comma(x) -> str:
    return fmt(x).replace(".", ",")


def normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("/прим/", "")).strip().lower()


def all_name_variants() -> dict:
    """Нормализованное название -> номер позиции (item_no). Нужен тестам и evaluate."""
    out = {}

    def add(name, item_no):
        key = normalize_name(name)
        if out.setdefault(key, item_no) != item_no:
            raise ValueError(f"название встречается у двух позиций: {name!r}")

    for it in ITEMS:
        for name in (it.name_a, it.name_b, it.name_c, LONG_NAMES.get(it.no)):
            if name:
                add(name, str(it.no))
    for n, (name_ab, name_c, _) in MATERIALS.items():
        add(name_ab, f"M{n}")
        add(name_c, f"M{n}")
    add(WASTE_NAME, "W1")
    for key, (name, *_rest) in EXTRAS.items():
        add(name, key)
    return out


def save_deterministic(wb: Workbook, path: Path) -> None:
    """Сохраняет книгу так, чтобы два запуска дали одинаковые байты:
    фиксируем свойства книги и метки времени внутри zip."""
    wb.properties.creator = "synthetic generator"
    wb.properties.lastModifiedBy = "synthetic generator"
    wb.properties.created = FIXED_DT
    buf = io.BytesIO()
    wb.save(buf)  # openpyxl при сохранении ставит modified = now, правим ниже
    zin = zipfile.ZipFile(buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in zin.namelist():
            data = zin.read(name)
            if name == "docProps/core.xml":
                text = data.decode("utf-8")
                text = re.sub(r"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                              r"\g<1>2025-01-01T00:00:00Z\g<2>", text)
                data = text.encode("utf-8")
            info = zipfile.ZipInfo(name, date_time=FIXED_DT.timetuple()[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            zout.writestr(info, data)


class Book:
    """Один xlsx с одним листом. put() пишет строку и возвращает её реальный номер."""

    def __init__(self, file_name: str, sheet: str, widths):
        self.file_name = file_name
        self.sheet = sheet
        self.wb = Workbook()
        self.ws = self.wb.active
        self.ws.title = sheet
        self.r = 0
        for i, w in enumerate(widths, 1):
            self.ws.column_dimensions[get_column_letter(i)].width = w

    def put(self, values, bold=False, merge_to=None) -> int:
        self.r += 1
        for c, v in enumerate(values, 1):
            if v is not None:
                cell = self.ws.cell(self.r, c, v)
                if bold:
                    cell.font = Font(bold=True)
        if merge_to:
            self.ws.merge_cells(start_row=self.r, start_column=1, end_row=self.r, end_column=merge_to)
        return self.r

    def blank(self) -> None:
        self.r += 1

    def save(self, out_dir: Path) -> Path:
        path = out_dir / self.file_name
        save_deterministic(self.wb, path)
        return path


class Generator:
    def __init__(self, seed: int = DEFAULT_SEED, out_dir=ROOT / "data" / "synthetic", meta_dir=ROOT / "data"):
        self.seed = seed
        self.out_dir = Path(out_dir)
        self.meta_dir = Path(meta_dir)
        self.rules = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
        self.log = []            # все записанные позиции: файл, лист, строка, item_no, количество...
        self.act_title_row = {}  # номер акта -> строка заголовка «Акт № N от ...»
        self.sheet_rows = {}     # файл -> число строк на листе
        self.paths = []
        self.seq = self._build_seq()
        self.est_total = 0.0

    # ---------- общее ----------
    def rng(self, name: str) -> random.Random:
        return random.Random(f"{self.seed}-{name}")

    def _build_seq(self):
        """Порядок строк в смете и ВОР-2: работа, затем её материал, затем мусор после неё."""
        seq = []
        for it in ITEMS:
            seq.append(("I", it.no))
            if it.no in MATERIALS:
                seq.append(("M", it.no))
            for idx, parent in enumerate(WASTE_PARENT):
                if parent == it.no:
                    seq.append(("W", idx))
        return seq

    @staticmethod
    def section_of(kind, ref):
        if kind == "I":
            return BY_NO[ref].section
        if kind == "M":
            return BY_NO[ref].section
        return BY_NO[WASTE_PARENT[ref]].section

    def seq_index(self, kind, ref):
        return self.seq.index((kind, ref))

    def item_no(self, kind, ref) -> str:
        return {"I": str(ref), "M": f"M{ref}", "W": "W1"}[kind]

    def record(self, book, row, doc, kind, ref, qty_norm, unit_text, act_no=None, price_norm=None, amount=None, tag=None):
        self.log.append({
            "file": book.file_name, "sheet": book.sheet, "row": row, "doc": doc,
            "item_no": self.item_no(kind, ref) if kind in "IMW" else ref,
            "qty_norm": round(qty_norm, 6), "unit": unit_text, "act_no": act_no,
            "price_norm": price_norm, "amount": amount, "tag": tag,
        })

    def spell(self, rng, unit):
        return rng.choice(UNIT_SPELL[unit])

    def vor_name(self, doc, kind, ref):
        if kind == "I":
            it = BY_NO[ref]
            return LONG_NAMES.get(ref) or (it.name_a if doc == "vor1" else it.name_b)
        if kind == "M":
            return MATERIALS[ref][0]
        return WASTE_NAME

    # ---------- формулы и мусор ----------
    def formula(self, rng, kind, ref, qty_norm):
        """Формула объёма текстом. Количество в ячейке остаётся числом и не пересчитывается."""
        if kind == "I" and ref in NORM:
            factor, _ = NORM[ref]
            unit = {"m2": "м2", "m3": "м3", "m": "м", "pcs": "шт"}[BY_NO[ref].unit]
            return f"{comma(qty_norm * factor)} {unit} / {factor} = {comma(qty_norm)}"
        r = rng.random()
        if r < 0.20:
            return f"по смете: {comma(qty_norm)}"
        if r < 0.34:
            part = round(qty_norm * 0.6, 1)
            return f"{comma(part)} + {comma(qty_norm - part)} = {comma(qty_norm)}"
        return None

    def pick_marks(self, rng, count, candidates):
        return set(rng.sample(candidates, count))

    # ---------- ВОР ----------
    def header_vor(self, b, ncols, subtitle):
        b.put(["Стройка: Капитальный ремонт СШ № 99 (синтетический объект)"], merge_to=ncols)
        b.put(["Объект: СШ № 99, вымышленный объект, синтетические данные"], merge_to=ncols)
        b.put([None] * (ncols - 2) + ["УТВЕРЖДАЮ"])
        b.put([None] * (ncols - 2) + [f"Директор (вымышленная должность) ________ {APPROVE_DATE}"])
        b.blank()
        b.put(["ВЕДОМОСТЬ ОБЪЁМОВ РАБОТ"], bold=True, merge_to=ncols)
        b.put([subtitle], merge_to=ncols)
        b.put(["Обоснование: дефектная ведомость № 1 (синтетические данные)"], merge_to=ncols)
        b.blank()

    def build_vor1(self):
        rng = self.rng("vor1")
        b = Book("vor_1.xlsx", "ВОР", [8, 60, 16, 10, 34, 22])
        self.header_vor(b, 6, "к локальной смете № 1")
        b.put(["№ п.п", "Наименование работ и затрат", "Ед. изм.", "Кол-во", "Формула расчёта объёма", "Примечание"], bold=True)
        b.put([1, 2, 3, 4, 5])
        items = [it for it in ITEMS if it.section in VOR1_SECTIONS]
        marks = self.pick_marks(rng, 4, [it.no for it in items])
        seq, count = 0, 0
        for sec_no, sec in enumerate(VOR1_SECTIONS, 1):
            b.put([f"Раздел {sec_no}. {SECTION_TITLE[sec]}"], bold=True, merge_to=6)
            for it in [i for i in items if i.section == sec]:
                if it.no == 8:
                    b.put([None, "Основания и подготовка"], bold=True)  # подзаголовок без номера
                if rng.random() < 0.10:
                    b.blank()
                seq += 1
                count += 1
                name = self.vor_name("vor1", "I", it.no) + (" /прим/" if it.no in marks else "")
                factor, unit_text = NORM.get(it.no, (1, None))
                unit_text = unit_text or self.spell(rng, it.unit)
                qty = it.qty / factor
                row = b.put([seq, name, unit_text, num(qty), self.formula(rng, "I", it.no, qty),
                             rng.choice(NOTES) if rng.random() < 0.10 else None])
                self.record(b, row, "vor", "I", it.no, it.qty, unit_text)
        b.blank()
        b.put([None, f"Всего по ведомости: {count} позиций"])
        b.blank()
        b.put([None, "Составил инженер-сметчик ________ (синтетические данные)"])
        self.finish(b)

    def build_vor2(self):
        rng = self.rng("vor2")
        b = Book("vor_2.xlsx", "ВОР", [10, 55, 55, 16, 10, 24, 40, 22])
        self.header_vor(b, 8, "к дефектной ведомости № 1")
        # колонка «Наименование работ» повторяется вместе с заголовком (дубль колонки)
        b.put(["№ в ЛСР", "Наименование работ", "Наименование работ", "Ед. изм.", "Кол-во",
               "Ссылка на чертежи, спецификации", "Формула расчёта, расчёт объёмов работ и расхода материалов",
               "Примечание"], bold=True)
        b.put([1, 2, 2, 3, 4, 5, 6])
        tokens = [(k, r) for (k, r) in self.seq if self.section_of(k, r) in VOR2_SECTIONS]
        marks = self.pick_marks(rng, 4, [r for (k, r) in tokens if k == "I"])
        seq, current = 0, None
        for kind, ref in tokens:
            sec = self.section_of(kind, ref)
            if sec != current:
                current = sec
                b.put([f"РАЗДЕЛ {VOR2_SECTIONS.index(sec) + 1}. {SECTION_TITLE[sec].upper()}"], bold=True, merge_to=8)
            if rng.random() < 0.10:
                b.blank()
            seq += 1
            name = self.vor_name("vor2", kind, ref) + (" /прим/" if kind == "I" and ref in marks else "")
            if kind == "I":
                it = BY_NO[ref]
                factor, unit_text = NORM.get(ref, (1, None))
                unit_text = unit_text or self.spell(rng, it.unit)
                qty_norm, qty = it.qty, it.qty / factor
                drawing = DRAWING_REF[sec]
            elif kind == "M":
                unit_text, qty_norm = MATERIALS[ref][2], BY_NO[ref].qty
                qty, drawing = qty_norm, f"спец. {DRAWING_REF[sec]}"
            else:
                unit_text, qty_norm = "1 т груза", WASTE_QTY[ref]
                qty, drawing = qty_norm, None
            row = b.put([seq, name, name, unit_text, num(qty), drawing, self.formula(rng, kind, ref, qty),
                         rng.choice(NOTES) if rng.random() < 0.10 else None])
            self.record(b, row, "vor", kind, ref, qty_norm, unit_text)
        b.blank()
        b.put([None, "Составил инженер-сметчик ________ (синтетические данные)"])
        self.finish(b)

    # ---------- смета ----------
    def build_estimate(self):
        rng = self.rng("estimate")
        b = Book("estimate.xlsx", "Смета", [8, 18, 60, 22, 10, 18, 18])
        b.put(["ЛОКАЛЬНАЯ СМЕТА № 1 (Локальный сметный расчёт)"], bold=True, merge_to=7)
        b.put(["Форма по мотивам формы 4, синтетическая. Цены текущие, ориентировочные, не рыночные"], merge_to=7)
        b.put(["Стройка: Капитальный ремонт СШ № 99 (синтетический объект)"], merge_to=7)
        b.blank()
        b.put(["№ поз.", "Шифр норматива", "Наименование", "Ед. изм.", "Кол-во", "Стоимость единицы, сом",
               "Общая стоимость, сом"], bold=True)
        current, seq, total = None, 0, 0.0
        for kind, ref in self.seq:
            sec = self.section_of(kind, ref)
            if sec != current:
                current = sec
                b.put([f"Раздел {SECTION_ORDER.index(sec) + 1}. {SECTION_TITLE[sec]}"], bold=True, merge_to=7)
            if rng.random() < 0.08:
                b.blank()
            seq += 1
            if kind == "I":
                it = BY_NO[ref]
                factor, unit_text = NORM.get(ref, (1, None))
                unit_text = unit_text or self.spell(rng, it.unit)
                qty, price = it.qty / factor, it.price * factor
                amount = round(qty * price, 2)
                total += amount
                code = f"Е{SECTION_ORDER.index(sec) + 1:02d}-{ref % 7 + 1:02d}-{ref * 3:03d}-01"
                row = b.put([seq, code, it.name_a, unit_text, num(qty), num(price), num(amount)])
                self.record(b, row, "estimate", kind, ref, it.qty, unit_text, price_norm=it.price, amount=amount)
            elif kind == "M":
                name, _, unit_text = MATERIALS[ref]
                row = b.put([seq, None, name, unit_text, num(BY_NO[ref].qty)])
                self.record(b, row, "estimate", kind, ref, BY_NO[ref].qty, unit_text)
            else:
                row = b.put([seq, None, WASTE_NAME, "1 т груза", num(WASTE_QTY[ref])])
                self.record(b, row, "estimate", kind, ref, WASTE_QTY[ref], "1 т груза")
        b.put([None, None, "Итого по смете, сом", None, None, None, num(total)], bold=True)
        b.blank()
        b.put([None, None, "Составил инженер-сметчик ________ (синтетические данные)"])
        self.est_total = total
        self.finish(b)

    # ---------- договор ----------
    def build_contract(self):
        b = Book("contract.xlsx", "Договор", [34, 60])
        b.put(["ДОГОВОР ПОДРЯДА № 12 (синтетический)"], bold=True, merge_to=2)
        b.put(["Заказчик", "Заказчик (вымышленная организация)"])
        b.put(["Подрядчик", "Подрядчик (вымышленная организация)"])
        b.put(["Объект", "СШ № 99 (синтетический объект)"])
        b.put(["Срок начала работ", CONTRACT_START])
        b.put(["Срок выполнения работ до", CONTRACT_DEADLINE])
        b.put(["Цена договора, сом", int(round(self.est_total / 1000.0) * 1000)])
        b.put(["Цен за единицу в договоре нет. Данные синтетические."], merge_to=2)
        for r in (5, 6):
            b.ws.cell(r, 2).number_format = "DD.MM.YYYY"
        self.finish(b)

    # ---------- акты ----------
    def build_act_rows(self):
        """Строки всех актов. Здесь же вносятся ошибки (FIXED_ROWS, PRICE_ALL, EXTRAS)."""
        rng = self.rng("facts")
        rows = []

        def add(act, kind, ref, qty, price=None, **extra):
            rows.append({"act": act, "kind": kind, "ref": ref, "qty": round(qty, 3), "price": price, **extra})

        for it in ITEMS:
            n = it.no
            if n in FIXED_ROWS:
                specs = FIXED_ROWS[n]
            else:
                pct = rng.choice([0.97, 0.98, 0.99, 1.0])
                fact = it.qty if it.unit == "pcs" else round(it.qty * pct, 1)
                acts = DEFAULT_ACTS[it.section]
                if len(acts) == 1:
                    specs = [(acts[0], fact, None)]
                else:
                    first = round(fact * 0.45) if it.unit == "pcs" else round(fact * 0.45, 1)
                    specs = [(acts[0], first, None), (acts[1], round(fact - first, 3), None)]
            for act, qty, price in specs:
                add(act, "I", n, qty, price, tag=ROW_TAG.get((n, act)))
                if n in MATERIALS:
                    add(act, "M", n, qty)
        for idx, act in enumerate(WASTE_ACT):
            add(act, "W", idx, WASTE_QTY[idx])
        for key, (name, unit, qty, price, act, tag) in EXTRAS.items():
            add(act, "X", key, qty, price, tag=tag)
        for r in rows:
            kind, ref = r["kind"], r["ref"]
            order = self.seq_index(kind, ref) if kind != "X" else 1000 + int(ref[1:])
            r["order"] = order
        rows.sort(key=lambda r: (r["act"], r["order"]))
        return rows

    def build_acts(self):
        act_rows = self.build_act_rows()
        for act_no, (date, tpl) in ACTS.items():
            rng = self.rng(f"act{act_no}")
            b = Book(f"act_{act_no}.xlsx", "Акт", [6, 58, 14, 14, 14, 18, 20])
            b.put(["Форма по мотивам КС-2, синтетическая"], merge_to=7)
            title = b.put([f"АКТ № {act_no} от {date.strftime('%d.%m.%Y')} о приёмке выполненных работ"],
                          bold=True, merge_to=7)
            self.act_title_row[act_no] = title
            b.put(["Объект: СШ № 99 (синтетический объект)"], merge_to=7)
            b.put(["Договор подряда № 12 (синтетический)"], merge_to=7)
            b.blank()
            if tpl == "a":
                b.put(["№", "Наименование выполненных работ", "Ед.", "Выполнено", "Цена", "Сумма", "Примечание"], bold=True)
            else:
                b.put(["№", "Работа", "Кол-во факт", "Изм.", "Тариф", "Итого по строке", "Примечание"], bold=True)
            total, seq = 0.0, 0
            for r in [r for r in act_rows if r["act"] == act_no]:
                kind, ref = r["kind"], r["ref"]
                if rng.random() < 0.08:
                    b.blank()
                seq += 1
                factor = 1
                price_plain = r["price"]
                if kind == "I":
                    it = BY_NO[ref]
                    variant = NAME_VARIANT_ACT.get(ref, "c")
                    name = it.name_b if variant == "b" else it.name_c
                    unit_text = FORCE_UNIT.get((ref, act_no)) or self.spell(rng, it.unit)
                    if price_plain is None:
                        price_plain = PRICE_ALL.get(ref, it.price)
                    if (ref, act_no) in ACT_NORM:
                        factor, unit_text = ACT_NORM[(ref, act_no)]
                elif kind == "M":
                    name, unit_text, price_plain = MATERIALS[ref][1], MATERIALS[ref][2], None
                elif kind == "W":
                    name, unit_text, price_plain = WASTE_NAME, self.spell(rng, "t"), None
                else:
                    name, unit, _, _, _, _ = EXTRAS[ref]
                    unit_text = self.spell(rng, unit)
                qty_shown = r["qty"] / factor
                price_shown = None if price_plain is None else price_plain * factor
                amount = None if price_plain is None else round(qty_shown * price_shown, 2)
                if amount is not None:
                    total += amount
                note = rng.choice(NOTES) if rng.random() < 0.08 else None
                if tpl == "a":
                    values = [seq, name, unit_text, num(qty_shown),
                              None if price_shown is None else num(price_shown),
                              None if amount is None else num(amount), note]
                else:
                    values = [seq, name, num(qty_shown), unit_text,
                              None if price_shown is None else num(price_shown),
                              None if amount is None else num(amount), note]
                row = b.put(values)
                self.record(b, row, "act", kind, ref, r["qty"], unit_text, act_no=act_no,
                            price_norm=price_plain, amount=amount, tag=r.get("tag"))
            b.put([None, "Итого по акту, сом", None, None, None, num(total)], bold=True)
            b.blank()
            b.put([None, "Сдал: Подрядчик (вымышленный) ________    Принял: Заказчик (вымышленный) ________"])
            self.finish(b)

    def finish(self, b: Book):
        self.paths.append(b.save(self.out_dir))
        self.sheet_rows[b.file_name] = b.r

    # ---------- ground truth, ловушки, ожидаемый светофор ----------
    def rows_of(self, item_no):
        order = {"vor_1.xlsx": 0, "vor_2.xlsx": 1, "estimate.xlsx": 2}
        rows = [r for r in self.log if r["item_no"] == item_no]
        rows.sort(key=lambda r: (order.get(r["file"], 3), r["file"], r["row"]))
        return ";".join(f"{r['file']}:{r['sheet']}:{r['row']}" for r in rows)

    def plan_fact(self):
        plan, fact = {}, {}
        for r in self.log:
            if r["doc"] == "vor":
                plan[r["item_no"]] = plan.get(r["item_no"], 0) + r["qty_norm"]
            elif r["doc"] == "act":
                fact[r["item_no"]] = fact.get(r["item_no"], 0) + r["qty_norm"]
        return {k: round(v, 6) for k, v in plan.items()}, {k: round(v, 6) for k, v in fact.items()}

    def canonical(self, item_no):
        if item_no.isdigit():
            return BY_NO[int(item_no)].name_a
        if item_no.startswith("M"):
            return MATERIALS[int(item_no[1:])][0]
        if item_no == "W1":
            return WASTE_NAME
        return EXTRAS[item_no][0]

    def build_ground_truth(self):
        tol = self.rules["volume_exceeded"]["tolerance_pct"]
        plan, _ = self.plan_fact()
        gt = []
        # объём: строка акта, где накопительная сумма впервые превысила допуск
        for gid, n in VOLUME_GT:
            item_no = str(n)
            acts = sorted((r for r in self.log if r["doc"] == "act" and r["item_no"] == item_no),
                          key=lambda r: (r["act_no"], r["row"]))
            cum, hit = 0.0, None
            for r in acts:
                cum += r["qty_norm"]
                if hit is None and cum > plan[item_no] * (1 + tol / 100.0) + 1e-9:
                    hit = r
            cum = round(cum, 6)
            gt.append({
                "gt_id": gid, "issue_type": "volume_exceeded",
                "scenario": "duplicate_in_two_acts" if n == 31 else "", "item_no": item_no,
                "canonical_name": BY_NO[n].name_a, "hit": hit, "related_rows": self.rows_of(item_no),
                "expected": plan[item_no], "actual": cum,
                "impact": round((cum - plan[item_no]) * BY_NO[n].price, 2),
            })
        # цена: строка акта с пометкой, цена за нормализованную единицу против сметы
        for tag, gid, n in PRICE_GT:
            hit = next(r for r in self.log if r["tag"] == tag)
            expected = BY_NO[n].price
            gt.append({
                "gt_id": gid, "issue_type": "price_increase", "scenario": "", "item_no": str(n),
                "canonical_name": BY_NO[n].name_a, "hit": hit, "related_rows": self.rows_of(str(n)),
                "expected": expected, "actual": hit["price_norm"],
                "impact": round((hit["price_norm"] - expected) * hit["qty_norm"], 2),
            })
        # позиции без ВОР
        for tag, gid, key in MISSING_GT:
            hit = next(r for r in self.log if r["tag"] == tag)
            gt.append({
                "gt_id": gid, "issue_type": "missing_in_vor", "scenario": "", "item_no": key,
                "canonical_name": EXTRAS[key][0], "hit": hit, "related_rows": self.rows_of(key),
                "expected": 0, "actual": hit["qty_norm"], "impact": round(hit["amount"], 2),
            })
        # акты после срока: строка заголовка
        for gid, act_no in ((11, 4), (12, 5)):
            date = ACTS[act_no][0]
            assert date > CONTRACT_DEADLINE
            file = f"act_{act_no}.xlsx"
            row = self.act_title_row[act_no]
            gt.append({
                "gt_id": gid, "issue_type": "late_act", "scenario": "", "item_no": "",
                "canonical_name": f"Акт №{act_no}",
                "hit": {"file": file, "sheet": "Акт", "row": row},
                "related_rows": f"{file}:Акт:{row}",
                "expected": CONTRACT_DEADLINE.isoformat(), "actual": date.isoformat(), "impact": None,
            })
        return gt

    def write_csvs(self, gt):
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        with open(self.meta_dir / "ground_truth.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(GT_COLUMNS)
            for g in gt:
                hit = g["hit"]
                exp, act = g["expected"], g["actual"]
                w.writerow([g["gt_id"], g["issue_type"], g["scenario"], g["item_no"], g["canonical_name"],
                            hit["file"], hit["sheet"], hit["row"], g["related_rows"],
                            exp if isinstance(exp, str) else fmt(exp), act if isinstance(act, str) else fmt(act),
                            "" if g["impact"] is None else fmt(g["impact"])])
        with open(self.meta_dir / "traps.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["trap_id", "item_no", "related_rows", "description"])
            for trap_id, item_no, text in TRAPS:
                w.writerow([trap_id, item_no, self.rows_of(item_no), text])
        plan, fact = self.plan_fact()
        red = {g["item_no"] for g in gt if g["issue_type"] != "late_act"}
        tol = self.rules["volume_exceeded"]["tolerance_pct"]
        under = self.rules["position_status"]["green_under_tolerance_pct"]
        keys = [str(it.no) for it in ITEMS] + [f"M{n}" for n in MATERIALS] + ["W1"] + list(EXTRAS)
        self.statuses = {}
        with open(self.meta_dir / "expected_status.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["item_no", "canonical_name", "plan_qty", "fact_qty", "expected_status"])
            for k in keys:
                p, q = plan.get(k), fact.get(k, 0)
                if k in red:
                    status = "red"
                else:
                    pct = q / p * 100
                    if pct > 100 + tol:
                        raise AssertionError(f"позиция {k} превышает допуск, но её нет в ground truth")
                    status = "green" if pct >= 100 - under else "yellow"
                self.statuses[k] = status
                w.writerow([k, self.canonical(k), "" if p is None else fmt(p), fmt(q), status])

    def run(self):
        self.build_vor1()
        self.build_vor2()
        self.build_estimate()
        self.build_contract()
        self.build_acts()
        gt = self.build_ground_truth()
        self.write_csvs(gt)
        self.gt = gt
        return self

    def summary(self) -> str:
        lines = ["Файлы:"]
        for path in self.paths:
            positions = sum(1 for r in self.log if r["file"] == path.name)
            lines.append(f"  {path.name}: позиций {positions}, строк на листе {self.sheet_rows[path.name]}")
        lines.append(f"  ground_truth.csv, traps.csv, expected_status.csv (в {self.meta_dir})")
        counts = {}
        for g in self.gt:
            counts[g["issue_type"]] = counts.get(g["issue_type"], 0) + 1
        lines.append(f"Заложенных расхождений: {len(self.gt)}")
        for t, c in counts.items():
            lines.append(f"  {t}: {c}")
        lines.append(f"Ловушек: {len(TRAPS)}")
        colors = {c: sum(1 for s in self.statuses.values() if s == c) for c in ("red", "yellow", "green")}
        lines.append(f"Ожидаемый светофор по {len(self.statuses)} ключам: {colors}")
        return "\n".join(lines)


def generate(seed: int = DEFAULT_SEED, out_dir=ROOT / "data" / "synthetic", meta_dir=ROOT / "data") -> Generator:
    return Generator(seed, out_dir, meta_dir).run()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Генератор синтетического демо-проекта")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", default=str(ROOT / "data" / "synthetic"), help="куда писать xlsx")
    parser.add_argument("--meta", default=str(ROOT / "data"), help="куда писать ground_truth.csv, traps.csv, expected_status.csv")
    args = parser.parse_args()
    print(generate(args.seed, args.out, args.meta).summary())


if __name__ == "__main__":
    main()
