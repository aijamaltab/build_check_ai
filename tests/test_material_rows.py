"""Предложение: строки-материалы не суммируются с работой (вопрос про «Кабель ВВГ-нг ...» в ВОР-2).

Это исполняемая спецификация правила. Кода парсера и matching в src/ ещё нет, поэтому прототип
(нормализация, классификация kind, сопоставление 1:1) живёт в этом файле и показывает, что правило
работает на синтетике. Когда появится реальный код, эти же проверки переносятся на него.

Правило (docs/synthetic_spec.md, §6; маркер «спец.» в templates.yaml, пороги и скореры в rules.yaml):
  1. kind = material, если в ВОР колонка чертежей начинается с маркера ИЛИ единица это существительное
     (units.yaml, noun_units). Иначе kind = work.
  2. work_key = kind + название + единица: материал и работа никогда не получают один ключ и не суммируются.
  3. Вне ВОР (смета, акты) признаков часто нет (единица «м»), поэтому kind наследуется от строки ВОР,
     с которой сопоставлена строка. Строки с известным kind сначала сопоставляются внутри своего kind.
     Сопоставление один к одному, жадно: внутри документа строка ВОР принимает только один ключ,
     а одинаковые ключи внутри документа сначала суммируются.
  4. Если kind определить нельзя (нет признака и нет пары в ВОР), ставится work и пишется
     dq-запись «kind не определён».
"""
import re

import pytest
import yaml
from rapidfuzz import fuzz

from tests.test_generate_synthetic import ACT_FILES, FILE_TEMPLATE, ROOT, UNITS, _clean, gen, read_csv, read_positions

TEMPLATES = yaml.safe_load((ROOT / "config" / "templates.yaml").read_text(encoding="utf-8"))["templates"]
MARKERS = tuple(TEMPLATES["vor_b"]["material_markers"]["drawing_ref_prefixes"])
SYN = yaml.safe_load((ROOT / "config" / "synonyms.yaml").read_text(encoding="utf-8"))
RULES = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
PAIRS = [("36", "M36"), ("37", "M37"), ("39", "M39"), ("40", "M40")]
PAIR_ITEMS = {x for p in PAIRS for x in p}


# ---------- прототип правила ----------
def proto_norm(name: str) -> str:
    """Нормализация по порядку из config/synonyms.yaml (без марок бетона)."""
    s = name.lower().replace("ё", "е")
    for m in SYN["strip_markers"]:
        s = s.replace(m, "")
    for pat, rep in SYN["token_rewrites"]:
        s = re.sub(pat, rep, s)
    for k, v in SYN["abbreviations"].items():
        s = s.replace(k, v)
    for canon, variants in SYN["synonyms"].items():
        for v in variants:
            s = re.sub(r"\b" + re.escape(v) + r"\b", canon, s)
    s = re.sub(r"[^\w\s.,×*]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_noun_unit(unit_text) -> bool:
    text = str(unit_text).strip()
    m = re.match(UNITS["multiplier"]["pattern"], text)
    rest = m.group(2) if m else text
    return _clean(rest) in {_clean(v) for vs in UNITS["noun_units"].values() for v in vs}


def signal(row):
    """Правило 1: признак материала, видимый в самой строке. Нет признака: None (kind неизвестен)."""
    ref = str(row.get("drawing_ref") or "").lower()
    if any(ref.startswith(m.lower()) for m in MARKERS) or is_noun_unit(row["unit"]):
        return "material"
    return None


def vor_kind(row) -> str:
    """В ВОР kind известен всегда: есть признак материала или это работа."""
    return signal(row) or "work"


def doc_key(row):
    return (proto_norm(row["name"]), row["unit_canon"])


def assign(doc_rows, vor_rows):
    """Правило 3: жадное сопоставление один к одному по убыванию (token_set, token_sort).
    Проход 1: строки с признаком материала только со строками ВОР того же kind.
    Проход 2: остальные строки со всеми свободными строками ВОР.
    Возвращает {ключ строки документа: строка ВОР}."""
    docs, vors = {}, {}
    for r in doc_rows:
        docs.setdefault(doc_key(r), r)
    for r in vor_rows:
        vors.setdefault(doc_key(r), r)
    out, used = {}, set()
    for known in (True, False):
        pairs = []
        for dk, d in docs.items():
            if dk in out or (signal(d) is not None) != known:
                continue
            for vk, v in vors.items():
                if vk in used or (known and vor_kind(v) != signal(d)):
                    continue
                a, b = proto_norm(d["name"]), proto_norm(v["name"])
                pairs.append(((fuzz.token_set_ratio(a, b), fuzz.token_sort_ratio(a, b)), dk, vk))
        pairs.sort(reverse=True)
        for (s1, _), dk, vk in pairs:
            if s1 < RULES["matching"]["llm_lower_bound"]:
                break
            if dk in out or vk in used:
                continue
            out[dk] = vors[vk]
            used.add(vk)
    return out


def kinds_with_dq(doc_rows, matched):
    """Правило 4: kind строки документа и список строк с «kind не определён»."""
    kinds, unknown = {}, []
    for r in doc_rows:
        v = matched.get(doc_key(r))
        if v is not None:
            kinds[r["row"]] = vor_kind(v)
        elif signal(r) is not None:
            kinds[r["row"]] = signal(r)
        else:
            kinds[r["row"]] = RULES["matching"]["kind_unknown_default"]
            unknown.append(r["row"])
    return kinds, unknown


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    base = tmp_path_factory.mktemp("materials")
    gen.generate(42, base / "files", base / "meta")
    data = {f: read_positions(base / "files" / f, t)[0] for f, t in FILE_TEMPLATE.items()}
    return {"data": data, "meta": base / "meta"}


# ---------- что происходит сейчас ----------
def test_exact_keys_of_work_and_material_differ(project):
    """По точному ключу (название + единица) пары НЕ сливаются и не суммируются: «прокладка», «ВВГ-нг»
    и «×» дают разные ключи. Опасность не здесь, а на этапе сопоставления."""
    for f in ("vor_2.xlsx", "estimate.xlsx", "act_3.xlsx"):
        rows = project["data"][f]
        for work, material in PAIRS:
            w = next(r for r in rows if r["item_no"] == work)
            m = next(r for r in rows if r["item_no"] == material)
            assert doc_key(w) != doc_key(m), (f, work)


def test_fuzzy_cannot_tell_led_material_from_its_work(project):
    """«Светильники LED» это подмножество слов «Светильники LED монтаж»: token_set_ratio = 100,
    то есть выше fuzzy_threshold. Без правила такие пары могут попасть в один кластер."""
    est = project["data"]["estimate.xlsx"]
    vor2 = project["data"]["vor_2.xlsx"]
    material = next(r for r in est if r["item_no"] == "M37")
    work = next(r for r in vor2 if r["item_no"] == "37")
    score = fuzz.token_set_ratio(proto_norm(material["name"]), proto_norm(work["name"]))
    assert score == 100 >= RULES["matching"]["fuzzy_threshold"]


def test_merging_work_and_material_would_corrupt_totals(project):
    """Если бы пара слилась в один ключ: план кабеля 2400 + 2400 = 4800 вместо 2400. Если слилась только
    часть строк (материал акта попал в ключ работы, материал ВОР остался отдельно): факт около 4650
    против плана 2400, то есть ложное «превышение» около 94%."""
    vor = {r["item_no"]: r["qty_norm"] for r in project["data"]["vor_2.xlsx"]}
    assert vor["36"] + vor["M36"] == 4800
    fact = {}
    for f in ACT_FILES:
        for r in project["data"][f]:
            fact[r["item_no"]] = fact.get(r["item_no"], 0) + r["qty_norm"]
    assert (fact["36"] + fact["M36"]) / vor["36"] > 1.9


# ---------- предложенное правило ----------
def test_static_markers_find_all_materials_in_vor2(project):
    kinds = {r["item_no"]: vor_kind(r) for r in project["data"]["vor_2.xlsx"]}
    assert {k for k, v in kinds.items() if v == "material"} == {"M36", "M37", "M39", "M40"}


def test_static_markers_alone_miss_materials_outside_vor2(project):
    """Известный пробел: в смете и актах у материалов «кабель» и «трубы» единица «м», колонки чертежей нет.
    Статические признаки находят только «светильник» и «радиатор», остальное закрывает наследование (правило 3)."""
    for f in ("estimate.xlsx", "act_3.xlsx"):
        found = {r["item_no"] for r in project["data"][f] if signal(r) == "material"}
        assert found == {"M37", "M39"}, f


def test_kind_inherited_through_one_to_one_matching(project):
    data = project["data"]
    vor = data["vor_1.xlsx"] + data["vor_2.xlsx"]
    for f in ["estimate.xlsx"] + ACT_FILES:
        matched = assign(data[f], vor)
        for r in data[f]:
            if r["item_no"] not in PAIR_ITEMS:
                continue
            v = matched[doc_key(r)]
            assert v["item_no"] == r["item_no"], (f, r["name"], v["name"])
            assert vor_kind(v) == ("material" if r["item_no"].startswith("M") else "work")


def test_work_and_material_totals_stay_separate(project):
    """Суммы по ключам kind:позиция равны ожидаемым из expected_status.csv и не удваиваются."""
    data = project["data"]
    vor = data["vor_1.xlsx"] + data["vor_2.xlsx"]
    plan, fact = {}, {}
    for r in vor:
        key = (vor_kind(r), r["item_no"])
        plan[key] = plan.get(key, 0) + r["qty_norm"]
    for f in ACT_FILES:
        matched = assign(data[f], vor)
        for r in data[f]:
            v = matched.get(doc_key(r))
            if v is None:
                continue
            key = (vor_kind(v), v["item_no"])
            fact[key] = fact.get(key, 0) + r["qty_norm"]
    expected = {r["item_no"]: r for r in read_csv(project["meta"] / "expected_status.csv")}
    for work, material in PAIRS:
        for item_no, kind in ((work, "work"), (material, "material")):
            assert plan[(kind, item_no)] == pytest.approx(float(expected[item_no]["plan_qty"]))
            assert fact[(kind, item_no)] == pytest.approx(float(expected[item_no]["fact_qty"]))
    assert plan[("work", "36")] == 2400 and plan[("material", "M36")] == 2400


def test_unknown_kind_defaults_to_work_and_is_reported(project):
    """Строка акта без признака и без пары в ВОР («отмостка», GT-9) получает work и dq-запись."""
    data = project["data"]
    vor = data["vor_1.xlsx"] + data["vor_2.xlsx"]
    rows = data["act_3.xlsx"]
    kinds, unknown = kinds_with_dq(rows, assign(rows, vor))
    x1 = next(r for r in rows if r["item_no"] == "X1")
    assert kinds[x1["row"]] == "work" and x1["row"] in unknown
    # материалы и их работы всегда определены; прочие несопоставленные строки (пробелы словаря) тоже в списке
    pair_rows = {r["row"] for r in rows if r["item_no"] in PAIR_ITEMS}
    assert not pair_rows & set(unknown)
    assert all(kinds[row] == "work" for row in unknown)
    assert RULES["matching"]["kind_unknown_dq_check"] == "kind не определён"


def test_config_declares_marker_scorers_and_key_format():
    assert MARKERS == ("спец.",)
    assert RULES["matching"]["scorers"] == ["token_set_ratio", "token_sort_ratio"]
    assert "WRatio" in RULES["matching"]["forbidden_scorers"]
    assert RULES["matching"]["work_key_format"].startswith("{kind}")
    assert RULES["matching"]["one_to_one"] is True
    assert RULES["evaluate"]["modes"] == ["no_synonyms", "synonyms", "synonyms_llm"]
