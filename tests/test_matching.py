"""Matching без ИИ: агрегация строк, exact и synonyms, fuzzy с защитами, ловушки из docs/synthetic_spec.md (§5).

Данные: синтетика генерируется во временную папку и загружается через ingestion в SQLite в памяти.
Эталон «какая строка к какой работе относится» берётся из журнала генератора (item_no каждой строки).
"""
import pytest

from src.config import load_config
from src.db import get_connection
from src.ingestion import ingest_dir
from src.matching import NameNormalizer, Row, build_groups, compute_matching, load_rows
from tests.test_generate_synthetic import gen

CFG = load_config()
M = CFG["rules"]["matching"]


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    generated = gen.generate(out_dir=out, meta_dir=out)
    conn = get_connection(":memory:")
    ingest_dir(conn, out, "demo", CFG)
    truth = {(r["file"], r["row"]): r["item_no"] for r in generated.log}
    return {"rows": load_rows(conn, "demo"), "truth": truth}


def truth_of(group, truth):
    return {truth[(r.file, r.source_row)] for r in group.rows}


def pairs_of(res, truth, item_no, doc_file=None):
    """Пары результата по позиции (по эталону строки документа)."""
    return [p for p in res.pairs if truth_of(p.doc, truth) == {item_no}
            and (doc_file is None or p.doc.first.file == doc_file)]


def row(item_id, name, unit="m2", qty=1.0, doc_id=1, doc_type="vor", kind="work", qty_raw=None, formula=None, src=None):
    """Строка для тестов без БД. name уже нормализован так же, как name_norm в ingestion (нижний регистр)."""
    return Row(item_id=item_id, doc_id=doc_id, doc_type=doc_type, file=f"f{doc_id}.xlsx", sheet="s",
               source_row=src or item_id, name_raw=name, unit_raw=unit, unit_norm=unit, quantity=qty, amount=None,
               name_norm=name.lower(), kind_hint=kind, quantity_raw=qty_raw or str(qty), formula_raw=formula, template=None)


# ---------- 1. агрегация строк одного ключа ----------
def test_waste_is_one_key_and_summed(project):
    norm = NameNormalizer(CFG["synonyms"], CFG["rules"])
    groups = [g for g in build_groups(project["rows"], norm, CFG) if g.name == "строительный мусор"]
    by_doc = {(g.doc_type, g.first.file): g for g in groups}
    assert len(by_doc[("vor", "vor_2.xlsx")].rows) == 6
    assert by_doc[("vor", "vor_2.xlsx")].qty_sum == pytest.approx(36.1)
    assert by_doc[("estimate", "estimate.xlsx")].qty_sum == pytest.approx(36.1)
    assert by_doc[("act", "act_1.xlsx")].qty_sum == pytest.approx(30.1)     # пять строк в акте №1, шестая в акте №3
    assert by_doc[("act", "act_3.xlsx")].qty_sum == pytest.approx(6.0)


def test_vor_groups_are_collected_per_project(project):
    norm = NameNormalizer(CFG["synonyms"], CFG["rules"])
    vor = [g for g in build_groups(project["rows"], norm, CFG) if g.is_vor]
    assert len(vor) == 45 and all(g.doc_id is None and g.kind in ("work", "material") for g in vor)   # 50 строк, мусор 6 -> 1


def test_full_duplicate_is_not_summed_but_repeated_name_with_other_quantity_is():
    norm = NameNormalizer(CFG["synonyms"], CFG["rules"])
    rows = [row(1, "стяжка пола", qty=10, formula="по смете: 10"), row(2, "стяжка пола", qty=10, formula="по смете: 10"),
            row(3, "строительный мусор", unit="t", qty=2), row(4, "строительный мусор", unit="t", qty=3)]
    dup, waste = build_groups(rows, norm, CFG)
    assert dup.qty_sum == 10 and dup.counted == {1: 1, 2: 0}               # второй полный дубль не входит в сумму
    assert waste.qty_sum == 5 and waste.counted == {3: 1, 4: 1}


def test_same_row_in_two_documents_is_not_a_duplicate():
    """GT-5: та же строка в двух актах это разные документы, обе строки идут в накопительную сумму."""
    norm = NameNormalizer(CFG["synonyms"], CFG["rules"])
    rows = [row(1, "стяжка пола", qty=700, doc_id=2, doc_type="act"), row(2, "стяжка пола", qty=700, doc_id=3, doc_type="act")]
    groups = build_groups(rows, norm, CFG)
    assert [g.qty_sum for g in groups] == [700, 700] and all(sum(g.counted.values()) == 1 for g in groups)


# ---------- 2. exact и synonyms ----------
def test_exact_stage_for_equal_keys(project):
    res = compute_matching(project["rows"], CFG)
    est = [p for p in res.pairs if p.doc.first.file == "estimate.xlsx" and p.stage == "exact"]
    assert len(est) >= 25 and all(p.score == 100 and p.method == "exact" for p in est)


def test_synonyms_stage_and_method_is_exact_in_contract_table(project):
    """«Шпаклевание стен» (акт) и «Шпаклёвка стен» (ВОР) совпадают только после словаря: stage synonyms, method exact."""
    res = compute_matching(project["rows"], CFG)
    found = [p for p in res.pairs if p.doc.name == p.vor.name and p.doc.first.name_norm != p.vor.first.name_norm]
    assert found and all(p.stage == "synonyms" and p.method == "exact" for p in found)
    assert any(p.doc.first.name_norm == "шпаклевание стен" for p in found)


def test_no_synonyms_mode_does_not_use_dictionary(project):
    res = compute_matching(project["rows"], CFG, use_synonyms=False)
    assert not any(p.stage == "synonyms" for p in res.pairs)
    syn = compute_matching(project["rows"], CFG, use_synonyms=True)
    assert len(syn.pairs) > len(res.pairs)                                  # словарь добавляет пары


def test_unit_must_match():
    rows = [row(1, "кладка стен", unit="m3"), row(2, "кладка стен", unit="m2", doc_id=2, doc_type="act")]
    assert compute_matching(rows, CFG).pairs == []


# ---------- 3. fuzzy, защиты, ловушки ----------
def test_trap4_multiplier_1000_m3_matches_and_quantities_equal(project):
    """Ловушка 4: ВОР «1000 м3» × 0,32 и акт 320 м3 после нормализации одна работа с равным объёмом."""
    res = compute_matching(project["rows"], CFG)
    pair = pairs_of(res, project["truth"], "6", "act_1.xlsx")
    assert pair == [] or pair[0].doc.qty_sum == pair[0].vor.qty_sum == 320     # если пары нет, это пробел словаря, не склейка
    est = pairs_of(res, project["truth"], "6", "estimate.xlsx")
    assert est and est[0].doc.qty_sum == est[0].vor.qty_sum == 320 and est[0].stage == "exact"


def test_trap5_waste_estimate_matches_vor_with_equal_sums(project):
    res = compute_matching(project["rows"], CFG)
    p = pairs_of(res, project["truth"], "W1", "estimate.xlsx")[0]
    assert (p.stage, p.doc.qty_sum, p.vor.qty_sum, len(p.vor.rows)) == ("exact", pytest.approx(36.1), pytest.approx(36.1), 6)


def test_trap6_rebar_d12_and_d8_never_merge(project):
    res = compute_matching(project["rows"], CFG)
    for p in res.pairs:                                                     # арматура d12 (№12) и d8 (№13) не смешиваются
        t = truth_of(p.doc, project["truth"]) | truth_of(p.vor, project["truth"])
        assert not ({"12", "13"} <= t), (p.doc.name, p.vor.name)
        if t & {"12", "13"}:
            assert truth_of(p.doc, project["truth"]) == truth_of(p.vor, project["truth"])
    norm = NameNormalizer(CFG["synonyms"], CFG["rules"])
    d12, d8 = norm.prepare("арматура а500 d12"), norm.prepare("арматура а240 d8")
    conflicts = norm.conflicts(d12, d8)
    assert norm.is_vetoed(conflicts) and {k for k, _ in conflicts} == {"patterns"}
    # те же диаметры в разных написаниях это одна арматура
    assert norm.conflicts(norm.prepare("арм. а500 ø12"), norm.prepare("арматурная сталь а-500с ф12")) == []


def test_trap6_act_row_d8_stays_a_candidate_for_its_own_position(project):
    """«Арматура гладкая Ø8» без класса А240 не блокируется числовыми токенами (missing_side: allow) и не сливается с d12."""
    res = compute_matching(project["rows"], CFG)
    rows = [c for c in res.candidates if c.doc.name == "арматура гладкая d8"]
    assert rows and all(truth_of(c.vor, project["truth"]) == {"13"} for c in rows)


def test_trap3_grade_equivalents_make_tokens_equal(project):
    """Ловушка 3: «Бетон М350 (перекрытия)» и «Бетон В25 для плит перекрытий» дают одинаковые числовые токены."""
    norm = NameNormalizer(CFG["synonyms"], CFG["rules"])
    a, b = norm.prepare("бетон м350 (перекрытия)"), norm.prepare("бетон в25 для плит перекрытий")
    assert a.tokens == b.tokens
    assert not norm.is_vetoed(norm.conflicts(a, b))
    # а М300 и В25 это разные марки: пару нельзя слить
    assert norm.is_vetoed(norm.conflicts(norm.prepare("бетон м300"), norm.prepare("бетон в25")))
    res = compute_matching(project["rows"], CFG)
    for p in pairs_of(res, project["truth"], "11"):
        assert truth_of(p.vor, project["truth"]) == {"11"}


def test_exclusive_words_and_brackets_block_merge_without_llm():
    """Нейтральная пара: «Внутренняя/Наружная перегородка (гипсокартон)» около 85: при пороге 85 слилась бы,
    защиты не дают, пара идёт в кандидаты для LLM (слова и скобки ИИ решить может, числовые токены нет)."""
    rows = [row(1, "внутренняя перегородка (гипсокартон)"),
            row(2, "наружная перегородка (гипсокартон)", doc_id=2, doc_type="act")]
    for threshold in (85, 90):
        res = compute_matching(rows, CFG, threshold=threshold)
        assert res.pairs == []
        assert len(res.candidates) == 1 and "слова группы" in res.candidates[0].reason
        assert res.blocked == []                                            # это не числовой конфликт
    plain = compute_matching(rows, CFG, use_synonyms=False, threshold=85)    # без защит базовый rapidfuzz слил бы
    assert len(plain.pairs) == 1


def test_brackets_conflict_goes_to_candidates():
    rows = [row(1, "труба (изолированная)", unit="m"), row(2, "труба (неизолированная)", unit="m", doc_id=2, doc_type="act")]
    res = compute_matching(rows, CFG, threshold=70)
    assert res.pairs == [] and "текст в скобках" in res.candidates[0].reason


def test_missing_side_policy_for_one_sided_brackets():
    rows = [row(1, "облицовка стен плиткой (санузлы)"), row(2, "облицовка стен плиткой", doc_id=2, doc_type="act")]
    assert compute_matching(rows, CFG, missing_side="block").pairs == []
    assert len(compute_matching(rows, CFG, missing_side="allow").pairs) == 1


def test_work_and_material_are_not_merged_by_kind():
    """«Монтаж светильников» (работа) и «Светильники LED» (материал, единица-существительное): token_set = 100,
    но у строки с единицей «светильник» признак материала известен, и она идёт только к материалам ВОР."""
    vor = [row(1, "светильники led монтаж", unit="pcs", kind="work"),
           row(2, "светильники led", unit="pcs", kind="material")]
    act = [row(3, "светильники led", unit="pcs", kind="material", doc_id=2, doc_type="act")]
    res = compute_matching(vor + act, CFG)
    assert [(p.doc.first.item_id, p.vor.first.item_id) for p in res.pairs] == [(3, 2)]
    # а без признака (единица «шт», как у работы) такая строка идёт к работе
    act_work = [row(4, "светильники led", unit="pcs", kind="work", doc_id=3, doc_type="act")]
    assert compute_matching(vor + act_work, CFG).pairs[0].vor.first.item_id in (1, 2)


def test_real_data_work_and_material_pairs_follow_truth(project):
    res = compute_matching(project["rows"], CFG)
    for item in ("37", "M37", "39", "M39"):
        for p in pairs_of(res, project["truth"], item):
            assert truth_of(p.vor, project["truth"]) == {item}


def test_no_false_merges_at_both_thresholds(project):
    """Ложные склейки по эталону генератора: нет ни при пороге 85, ни при 90 (с правилом «подмножество»)."""
    for threshold in CFG["rules"]["evaluate"]["thresholds"]:
        res = compute_matching(project["rows"], CFG, threshold=threshold)
        wrong = [(p.doc.first.file, p.doc.first.source_row) for p in res.pairs
                 if truth_of(p.doc, project["truth"]) != truth_of(p.vor, project["truth"])]
        assert wrong == [], (threshold, wrong)


# ---------- правило «подмножество» (subset_review_below) ----------
def cfg_with(**overrides):
    import copy
    cfg = copy.deepcopy(CFG)
    cfg["rules"]["matching"].update(overrides)
    return cfg


def test_subset_rule_cable_material_goes_to_review_not_to_work(project):
    """Раньше (известная ложная склейка): материал акта «Кабель ВВГ-нг 3х2,5» (единица «м», признака нет) — подмножество слов
    работы «Кабель ВВГ-нг 3х2.5 прокладка», token_set_ratio = 100, и жадный выбор отдавал ему работу ВОР.
    Теперь пара с token_sort_ratio ниже subset_review_below и конкурентом другого kind не склеивается автоматически."""
    res = compute_matching(project["rows"], CFG)
    act3 = [g for g in res.groups if g.first.file == "act_3.xlsx" and truth_of(g, project["truth"]) == {"M36"}][0]
    assert res.pair_of(act3.gid) is None or truth_of(res.pair_of(act3.gid).vor, project["truth"]) == {"M36"}
    work = next(g for g in res.groups if g.is_vor and truth_of(g, project["truth"]) == {"36"})
    pair = res.pair_of(act3.gid)
    assert pair is None or pair.vor.gid != work.gid
    # а при отключённом правиле та же склейка возвращается (это то, что правило предотвращает)
    off = compute_matching(project["rows"], cfg_with(subset_review_below=0, competitor_review=False, name_similarity="plain"))
    bad = [p for p in off.pairs if truth_of(p.doc, project["truth"]) != truth_of(p.vor, project["truth"])]
    assert len(bad) == 1 and truth_of(bad[0].doc, project["truth"]) == {"M36"} and bad[0].score == 100


def test_subset_rule_led_lamps_against_work_with_installation():
    """«Светильники LED» против «Светильники LED монтаж»: token_set = 100, token_sort ниже порога подмножества."""
    vor_work = row(1, "светильники led монтаж", unit="pcs", kind="work")
    act = row(3, "светильники led", unit="pcs", kind="work", doc_id=2, doc_type="act")
    res = compute_matching([vor_work, act], cfg_with(subset_review_scope="always"))
    assert res.pairs == [] and "подмножество" in res.candidates[0].reason and res.state_of(res.unmatched[0]) == "ambiguous"
    # режим competitor: без материала-конкурента в ВОР пара склеивается (это обычное короткое название работы)
    assert len(compute_matching([vor_work, act], CFG).pairs) == 1
    # с конкурентом другого kind (материал «светильники led секционные») пара уходит на проверку
    vor_material = row(2, "светильники led секционные", unit="pcs", kind="material")
    res = compute_matching([vor_work, vor_material, act], CFG)
    assert [p.vor.first.item_id for p in res.pairs] != [1]
    assert res.state_of(res.unmatched[0]) == "ambiguous" or res.pairs[0].vor.first.item_id == 2


def test_subset_rule_off_in_baseline_mode_and_for_equal_names():
    vor = row(1, "светильники led монтаж", unit="pcs")
    act = row(3, "светильники led", unit="pcs", doc_id=2, doc_type="act")
    assert len(compute_matching([vor, act], CFG, use_synonyms=False, threshold=85).pairs) == 1   # базовая линия без правила
    same = row(4, "светильники led монтаж", unit="pcs", doc_id=3, doc_type="act")
    assert compute_matching([vor, same], cfg_with(subset_review_scope="always")).pairs[0].stage == "exact"


# ---------- три состояния ----------
def test_states_matched_ambiguous_absent():
    vor = [row(1, "кладка стен", unit="m3"), row(2, "утепление фасада плитами", unit="m2")]
    act = [row(3, "кладка стен", unit="m3", doc_id=2, doc_type="act"),                    # matched
           row(4, "утепл. фасада минватой", unit="m2", doc_id=2, doc_type="act"),         # похоже: есть кандидат -> ambiguous
           row(5, "видеонаблюдение система", unit="set", doc_id=2, doc_type="act")]       # ничего похожего -> absent
    res = compute_matching(vor + act, CFG)
    states = {g.first.item_id: res.state_of(g) for g in res.groups if not g.is_vor}
    assert states == {3: "matched", 4: "ambiguous", 5: "absent"}
    assert [g.first.item_id for g in res.absent] == [5] and [g.first.item_id for g in res.ambiguous] == [4]


def test_only_absent_is_a_missing_in_vor_candidate_in_real_data(project):
    res = compute_matching(project["rows"], CFG)
    true_missing = {g.first.item_id for g in res.groups if not g.is_vor and truth_of(g, project["truth"]) <= {"X1", "X2"}}
    absent = {g.first.item_id for g in res.absent}
    assert true_missing <= absent                      # отмостка и видеонаблюдение ловятся как absent (кандидат на «монтаж» не строится)
    assert CFG["rules"]["matching"]["unmatched_issue_only_state"] == "absent"


# ---------- сходство названий: стемминг и сокращения, без стоп-слов ----------
def test_stemmed_similarity_handles_endings_and_abbreviations():
    vor = row(1, "демонтаж дверных блоков", unit="pcs")
    act = row(2, "демонтаж дверн. блоков", unit="pcs", doc_id=2, doc_type="act")          # сокращение: «дверн.» это начало «дверных»
    stemmed = compute_matching([vor, act], CFG)
    plain = compute_matching([vor, act], cfg_with(name_similarity="plain"))
    assert len(stemmed.pairs) == len(plain.pairs) == 1
    assert stemmed.pairs[0].score == 100 > plain.pairs[0].score                             # стемминг поднимает оценку пары
    endings = [row(3, "утепление стен минераловатными плитами", unit="m2"),
               row(4, "утепление стен минераловатными плитами", unit="m2", doc_id=2, doc_type="act")]
    assert compute_matching(endings, CFG).pairs[0].stage == "exact"


def test_verbs_are_not_stop_words_montage_is_not_demontage():
    """Стоп-слова не удаляются: иначе «монтаж покрытия» и «демонтаж покрытий» становятся почти одинаковыми."""
    vor = row(1, "демонтаж покрытий полов из линолеума и поливинилхлоридных плиток", unit="m2")
    act = row(2, "монтаж покрытия из линолеума", unit="m2", doc_id=2, doc_type="act")
    assert compute_matching([vor, act], CFG).pairs == []
    assert not CFG["rules"]["matching"].get("stop_words")
    assert "монтаж" in CFG["rules"]["matching"]["candidate_ignore_words"]                  # но кандидатов на одном глаголе не строим


def test_candidate_is_not_built_on_a_shared_verb_only():
    vor = row(1, "монтаж опалубки", unit="m2")
    act = row(2, "монтаж отмостки вокруг здания", unit="m2", doc_id=2, doc_type="act")
    res = compute_matching([vor, act], CFG)
    assert res.pairs == [] and res.candidates == [] and res.state_of(res.unmatched[0]) == "absent"
    # но с общим существенным словом кандидат остаётся
    vor2 = row(4, "монтаж щитовой опалубки", unit="m2")
    act2 = row(3, "монтаж опалубки колонн", unit="m2", doc_id=3, doc_type="act")
    assert compute_matching([vor2, act2], CFG, threshold=95).candidates


def test_competitor_review_pipes_material_does_not_take_the_work():
    """«Трубы полипропиленовые ППР» (единица «м», признака материала нет) не должны занять работу «Прокладка трубопроводов…»,
    когда в ВОР есть похожий материал «Трубы ППР»."""
    work = row(1, "прокладка трубопроводов отопления из полипропиленовых труб диаметром до 32 мм", unit="m", kind="work")
    material = row(2, "трубы ппр", unit="m", kind="material")
    act = row(3, "трубы полипропиленовые ппр", unit="m", kind="work", doc_id=2, doc_type="act")
    res = compute_matching([work, material, act], CFG)
    assert all(p.vor.first.item_id != 1 for p in res.pairs)
    off = compute_matching([work, material, act], cfg_with(competitor_review=False))
    assert off.pairs                                                                        # правило включено не зря: без него пара есть


def test_real_data_no_false_merges_and_numbers_are_never_touched(project):
    """Matching не меняет ни одного числа и не склеивает разные работы (в том числе строки ловушек +3% объёма и +2% цены)."""
    conn = get_connection(":memory:")
    from tests.test_generate_synthetic import gen as g
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        g.generate(out_dir=tmp, meta_dir=tmp)
        ingest_dir(conn, tmp, "demo", CFG)
    before = conn.execute("SELECT item_id, quantity, unit_price, amount FROM items ORDER BY item_id").fetchall()
    from src.matching import save_matching
    res = compute_matching(load_rows(conn, "demo"), CFG)
    save_matching(conn, res, "demo", CFG)
    after = conn.execute("SELECT item_id, quantity, unit_price, amount FROM items ORDER BY item_id").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]
    for p in res.pairs:
        assert truth_of(p.doc, project["truth"]) == truth_of(p.vor, project["truth"]), (p.doc.name, p.vor.name)
    traps = {"17", "32", "6", "W1"}
    trap_pairs = [p for p in res.pairs if truth_of(p.doc, project["truth"]) & traps]
    assert trap_pairs                                                                       # ловушечные позиции сопоставляются правильно
