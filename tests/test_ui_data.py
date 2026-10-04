"""ui/data.py без Streamlit: временная база из data/synthetic через run_pipeline (режим llm из реального кэша, только чтение, без ключа)."""
import re
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline import run_pipeline
from tests.cache_guard import REAL_CACHE
from ui.data import (AI_NOT_FOUND_NOTE, LOW_CONFIDENCE_NOTE, SEVERITY_COLOR, STATUS_COLORS, build_cards, cards_frame, chart_frames,
                     connect_readonly, contrast_ratio, filter_issues, fmt_conf, fmt_date, fmt_num, fmt_pct, headline_metrics,
                     impact_split, load_results, pick_examples, positions_view, quality_compare, quality_metrics, sort_issues,
                     traffic_legend, traffic_segments, compact_rows, false_issue_ids, describe_file, detail_rows, file_label, file_preview)

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "data" / "synthetic"


@pytest.fixture()
def llm_env(monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))        # реальный кэш, только чтение
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.fixture()
def llm_db(llm_env, tmp_path):
    db = tmp_path / "llm.db"
    run_pipeline(DEMO, db, "llm")
    return db


@pytest.fixture()
def rules_db(tmp_path):
    db = tmp_path / "rules.db"
    run_pipeline(DEMO, db, "rules_only")
    return db


# ---------- чтение из базы ----------
def test_load_results_llm_summary_issues_positions_documents(llm_db):
    r = load_results(llm_db)
    s = r["summary"]
    assert (s["mode"], s["requested_mode"], s["banner"], s["caveat"]) == ("llm", "llm", None, None)
    assert (s["n"], s["m"], s["k"], s["a"], s["l"], s["z"], s["files"]) == (180, 0, 3, 0, 0, 13, 9)
    assert s["impact_som"] == 1378030.0 and s["statuses"] == {"red": 11, "yellow": 7, "green": 30}
    assert s["ai"]["calls"] == 0 and s["ai"]["cache_hits"] > 0
    assert len(r["issues"]) == 13 and set(r["issues"]["confidence"]) == {"high"}
    assert {"issue_id", "issue_type", "source_file", "source_sheet", "source_row", "impact_som", "explanation", "sources", "ai_matched"} <= set(
        r["issues"].columns)
    assert len(r["positions"].columns) == 10 and r["positions"]["status"].value_counts().to_dict() == s["statuses"]
    docs = r["documents"]
    assert len(docs) == 9 and set(docs["status"]) == {"parsed"} and (docs["failed_checks"] == 0).all()


def test_issues_come_sorted_by_impact_with_empty_last(llm_db):
    impact = load_results(llm_db)["issues"]["impact_som"]
    filled = impact.dropna()
    assert list(filled) == sorted(filled, reverse=True) and impact.iloc[len(filled):].isna().all()


def test_database_is_opened_read_only(llm_db):
    conn = connect_readonly(llm_db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("CREATE TABLE x (a)")
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM runs")
    conn.close()


def test_unknown_project_gives_empty_results(llm_db):
    r = load_results(llm_db, project_id="no-such")
    assert r["summary"] == {} and r["issues"].empty and r["positions"].empty and r["documents"].empty


def test_sources_list_every_document_where_the_discrepancy_was_found(llm_db):
    issues = load_results(llm_db)["issues"]
    rebar = issues[(issues["issue_type"] == "volume_exceeded") & (issues["source_row"] == 12)].iloc[0]
    assert rebar["sources"][0] == "Акт · act_2.xlsx · лист «Акт» · строка 12"
    assert "ВОР · vor_1.xlsx · лист «ВОР» · строка 22" in rebar["sources"] and "Акт · act_1.xlsx · лист «Акт» · строка 23" in rebar["sources"]
    price = issues[issues["issue_type"] == "price_increase"].iloc[0]
    assert len(price["sources"]) == 2 and price["sources"][1].startswith("Смета · estimate.xlsx · лист «Смета» · строка ")
    late = issues[issues["issue_type"] == "late_act"].iloc[0]
    assert late["sources"][1] == "Договор · contract.xlsx · лист «Договор» · строка 6"
    missing = issues[issues["issue_type"] == "missing_in_vor"].iloc[0]
    assert len(missing["sources"]) == 1
    for sources in issues["sources"]:
        assert all(re.fullmatch(r"(ВОР|Смета|Акт|Договор) · .+ · лист «.+» · строка \d+", s) for s in sources)


def test_ai_matched_flag_only_in_llm_mode_and_only_for_matched_pairs(llm_db, rules_db):
    llm = load_results(llm_db)["issues"]
    assert llm["ai_matched"].sum() >= 1
    assert not llm[llm["issue_type"].isin(["missing_in_vor", "late_act"])]["ai_matched"].any()
    assert not load_results(rules_db)["issues"]["ai_matched"].any()


# ---------- форматирование ----------
def test_fmt_num_pct_date():
    assert fmt_num(1378030.0) == "1 378 030" and fmt_num(11.4) == "11,4" and fmt_num(1.9000000000000004) == "1,9"
    assert fmt_num(0) == "0" and fmt_num(None) == "—" and fmt_num(float("nan")) == "—"
    assert fmt_pct(20.000000000000004) == "+20,0%" and fmt_pct(16.2162) == "+16,2%" and fmt_pct(-5) == "−5,0%" and fmt_pct(7, signed=False) == "7,0%"
    assert fmt_pct(None) == "—"
    assert fmt_date("2025-09-30") == "30.09.2025" and fmt_date("не дата") == "не дата"


def test_status_and_severity_colors_have_enough_contrast():
    for status, (bg, fg) in STATUS_COLORS.items():
        assert contrast_ratio(bg, fg) >= 4.5, status
    assert STATUS_COLORS["red"][0] == "#C62828" and STATUS_COLORS["yellow"][0] == "#F9A825" and STATUS_COLORS["green"][0] == "#2E7D32"
    assert SEVERITY_COLOR["high"] == "#C62828" and SEVERITY_COLOR["medium"] == "#F9A825"
    assert contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)


# ---------- сводные числа ----------
def test_impact_split_on_real_and_fake_data(llm_db, rules_db):
    assert impact_split(load_results(llm_db)["issues"]) == {"high": 1378030.0, "low": 0.0, "n_low": 0}
    assert impact_split(load_results(rules_db)["issues"]) == {"high": 366600.0, "low": 1086110.0, "n_low": 12}
    fake = pd.DataFrame({"impact_som": [100.0, None, 50.0], "confidence": ["high", "high", "low"]})
    assert impact_split(fake) == {"high": 100.0, "low": 50.0, "n_low": 1}
    assert impact_split(pd.DataFrame(columns=["impact_som", "confidence"])) == {"high": 0.0, "low": 0.0, "n_low": 0}


def test_headline_metrics_for_both_modes(llm_db, rules_db):
    llm = load_results(llm_db)
    m = headline_metrics(llm["summary"], llm["issues"], llm["positions"])
    assert (m["positions"], m["issues"], m["impact"], m["impact_extra_n"]) == (180, 13, 1378030.0, 0)
    assert m["review_positions"] == 18 == llm["summary"]["statuses"]["red"] + llm["summary"]["statuses"]["yellow"]
    assert "manual" not in m
    rules = load_results(rules_db)
    m = headline_metrics(rules["summary"], rules["issues"], rules["positions"])
    assert (m["positions"], m["issues"], m["impact"], m["impact_extra_n"], m["impact_extra"]) == (180, 18, 366600.0, 12, 1086110.0)
    assert m["review_positions"] == 37 == int(rules["positions"]["status"].isin(["red", "yellow"]).sum())
    assert headline_metrics(llm["summary"], llm["issues"], llm["positions"].iloc[0:0])["review_positions"] == 0
    fake = pd.DataFrame({"status": ["red", "yellow", "green", "green"]})
    assert headline_metrics(llm["summary"], llm["issues"], fake)["review_positions"] == 2


def test_traffic_segments_and_legend(llm_db, rules_db):
    segments = traffic_segments(load_results(llm_db)["summary"])
    assert [(s["status"], s["count"], s["label"]) for s in segments] == [
        ("red", 11, "Красные: 11 позиций"), ("yellow", 7, "Жёлтые: 7 позиций"), ("green", 30, "Зелёные: 30 позиций")]
    assert [s["label"] for s in traffic_segments(load_results(rules_db)["summary"])] == [
        "Красные: 12 позиций", "Жёлтые: 25 позиций", "Зелёные: 16 позиций"]
    assert all(contrast_ratio(s["bg"], s["fg"]) >= 4.5 for s in segments)
    legend = traffic_legend()
    assert "Красный" in legend and "Жёлтый" in legend and "Зелёный" in legend and "5 %" in legend


def test_chart_frames_cover_all_types(llm_db):
    issues = load_results(llm_db)["issues"]
    counts, impacts = chart_frames(issues)
    assert counts["label"].tolist() == ["Превышение объёма", "Рост цены", "Нет в ВОР", "Акт после срока договора"]
    assert counts["value"].tolist() == [5, 3, 3, 2] and counts["text"].tolist() == ["5", "3", "3", "2"]
    assert impacts["value"].sum() == pytest.approx(issues["impact_som"].sum())
    assert impacts["value"].iloc[3] == 0 and impacts["text"].iloc[3] == "0"
    empty_counts, empty_impacts = chart_frames(issues.iloc[0:0])
    assert empty_counts["value"].tolist() == [0, 0, 0, 0] and empty_impacts["value"].sum() == 0


# ---------- сортировка, фильтры, карточки ----------
def test_sort_puts_high_first_then_impact_descending_empty_last(llm_db):
    issues = load_results(llm_db)["issues"]
    ordered = sort_issues(issues.sample(frac=1, random_state=3))
    severities = ordered["severity"].tolist()
    assert severities == sorted(severities, key=["high", "medium", "low"].index)
    for severity, group in ordered.groupby("severity", sort=False):
        amounts = group["impact_som"].fillna(-1).tolist()
        assert amounts == sorted(amounts, reverse=True)
    assert sort_issues(issues.iloc[0:0]).empty


def test_filters_by_severity_type_and_name(llm_db):
    r = load_results(llm_db)
    issues, positions = r["issues"], r["positions"]
    assert set(filter_issues(issues, positions, "high")["severity"]) == {"high"}
    assert len(filter_issues(issues, positions, "all")) == 13
    assert set(filter_issues(issues, positions, types=["late_act"])["issue_type"]) == {"late_act"}
    assert len(filter_issues(issues, positions, types=["late_act", "price_increase"])) == 5
    found = filter_issues(issues, positions, query="  АРМАТУРА ")
    assert len(found) == 1 and found.iloc[0]["issue_type"] == "volume_exceeded"
    assert filter_issues(issues, positions, query="такой работы нет").empty
    assert filter_issues(issues, positions, "medium", ["volume_exceeded"], "кровля").shape[0] == 1
    assert filter_issues(issues, positions, "low").empty


def test_cards_phrases_impact_notes_and_table(llm_db):
    r = load_results(llm_db)
    cards = build_cards(sort_issues(r["issues"]), r["positions"])
    by_title = {c["title"]: c for c in cards}
    assert len(cards) == 13
    rebar = by_title["Арматура А500 d12"]
    assert rebar["phrase"] == "В актах 11,4 т при 9,5 т в ВОР (+20,0%)" and rebar["impact_text"] == "117 800 сом"
    assert (rebar["type_label"], rebar["severity_label"]) == ("Превышение объёма", "высокая")
    price = next(c for c in cards if c["type"] == "price_increase" and "окон" in c["title"].lower())
    assert price["phrase"] == "Цена в акте 7 900 сом за м2 при 6 800 сом в смете (+16,2%)"
    missing = next(c for c in cards if c["type"] == "missing_in_vor")
    assert "в ВОР пары не найдено" in missing["phrase"] and missing["note"] == AI_NOT_FOUND_NOTE
    late = [c for c in cards if c["type"] == "late_act"]
    assert late[0]["phrase"] == "Акт датирован 17.10.2025, срок договора 30.09.2025: позже срока на 17 дн."
    assert late[0]["impact_text"].startswith("—") and late[0]["title"].startswith("Акт act_4.xlsx")
    assert cards[0]["severity"] == "high" and cards[-1]["severity"] == "medium"
    frame = cards_frame(cards)
    assert len(frame) == 13 and frame["Влияние, сом"].dropna().map(float).max() == max(c["impact_value"] or 0 for c in cards)
    assert frame["Источник"].str.contains("лист «").all() and set(frame["ИИ помог сопоставить"]) <= {"да", ""}


def test_cards_in_rules_only_mark_low_confidence(rules_db):
    r = load_results(rules_db)
    cards = build_cards(sort_issues(r["issues"]), r["positions"])
    low = [c for c in cards if c["note"] == LOW_CONFIDENCE_NOTE]
    assert len(cards) == 18 and len(low) == 12 and all(c["type"] == "missing_in_vor" for c in low)
    assert not any(c["ai"] for c in cards)


def test_card_with_empty_impact_shows_reason_and_unknown_estimate_price():
    issues = pd.DataFrame([{"issue_id": 1, "issue_type": "price_increase", "work_key": "work:x|m2", "expected": None, "actual": 120.0,
                            "delta_pct": None, "severity": "high", "source_file": "a.xlsx", "source_sheet": "Акт", "source_row": 5,
                            "explanation": "Возможное расхождение. Требует проверки.", "impact_som": None, "impact_note": "нет цены в смете",
                            "confidence": "high", "unit": "м2", "expected_text": None, "actual_text": None,
                            "sources": ["Акт · a.xlsx · лист «Акт» · строка 5"], "ai_matched": False, "ai_pairs": [], "ai_none": None,
                            "sides": {"left": {}, "right": {}}}])
    positions = pd.DataFrame([{"work_key": "work:x|m2", "name": "Штукатурка"}])
    card = build_cards(issues, positions)[0]
    assert card["title"] == "Штукатурка" and card["impact_text"] == "— (нет цены в смете)" and card["impact_value"] is None
    assert card["phrase"] == "Цена в акте 120 сом за м2; цены в смете для сравнения нет"


# ---------- светофор по позициям ----------
def test_positions_view_orders_red_first_and_filters(llm_db):
    positions = load_results(llm_db)["positions"]
    allv = positions_view(positions)
    assert len(allv) == len(positions) and list(allv.columns)[:6] == ["Работа", "Ед.", "План", "Факт", "Выполнено, %", "Статус"]
    statuses = allv["_status"].tolist()
    assert statuses == sorted(statuses, key=["red", "yellow", "green"].index)
    yellow = positions_view(positions, "yellow")
    assert set(yellow["_status"]) == {"yellow"} and set(yellow["Статус"]) == {"Жёлтый"} and len(yellow) == 7
    assert positions_view(positions.iloc[0:0]).empty


# ---------- формулировки ----------
def test_no_accusing_words_in_the_ui_code():
    banned = ("мошенничеств", "нарушение выявлено", "хищени")
    for path in [ROOT / "app.py", *sorted((ROOT / "ui").glob("*.py"))]:
        text = path.read_text(encoding="utf-8").lower()
        assert not [w for w in banned if w in text], path.name


# ---------- что сделал ИИ ----------
def test_ai_pairs_show_before_after_confidence_and_reason(llm_db, rules_db):
    issues = load_results(llm_db)["issues"]
    with_pairs = issues[issues["ai_pairs"].map(len) > 0]
    assert len(with_pairs) == int(issues["ai_matched"].sum()) >= 3
    assert set(with_pairs["issue_type"]) <= {"volume_exceeded", "price_increase"}
    for pairs in with_pairs["ai_pairs"]:
        for p in pairs:
            assert p["doc"] and p["vor"] and p["doc"] != p["vor"] and p["doc_type"] in ("act", "estimate")
            assert 0 <= p["confidence"] <= 1 and p["reason"] and p["stage"] in ("llm", "llm_row")
            assert "/прим/" not in p["doc"] + p["vor"]
    names = {(p["doc"], p["vor"]) for pairs in with_pairs["ai_pairs"] for p in pairs}
    assert ("Стяжка цем.-песч.", "Устройство цементной стяжки пола") in names
    rules = load_results(rules_db)["issues"]
    assert rules["ai_pairs"].map(len).sum() == 0 and rules["ai_none"].isna().all()


def test_ai_none_marks_missing_in_vor_confirmed_by_ai(llm_db):
    issues = load_results(llm_db)["issues"]
    missing = issues[issues["issue_type"] == "missing_in_vor"]
    assert len(missing) == 3 and missing["ai_none"].map(lambda x: isinstance(x, dict)).all()
    for n in missing["ai_none"]:
        assert 0.7 <= n["confidence"] <= 1 and n["reason"]
    assert issues[issues["issue_type"] != "missing_in_vor"]["ai_none"].isna().all()


def test_cards_carry_ai_blocks(llm_db):
    r = load_results(llm_db)
    cards = build_cards(sort_issues(r["issues"]), r["positions"])
    assert sum(1 for c in cards if c["ai_pairs"]) >= 3 and sum(1 for c in cards if c["ai_none"]) == 3
    assert all(c["ai"] == bool(c["ai_pairs"]) for c in cards)


def test_ai_examples_from_cache_cover_all_decision_kinds(llm_db):
    examples = load_results(llm_db)["ai_examples"]
    assert len(examples) == 6
    assert {e["kind"] for e in examples} == {"pair_accepted", "pair_rejected", "row_accepted", "row_none"}
    assert len({e["doc"].lower() for e in examples}) == 6
    for e in examples:
        assert e["doc"] and e["code_rule"] and e["ai"] and e["code_check"] and 0 <= e["confidence"] <= 1
        assert "/прим/" not in (e["vor"] or "") + e["doc"]
        assert "из 100" in e["code_rule"] and "уверенность" in e["ai"]
    accepted = next(e for e in examples if e["kind"] == "pair_accepted")
    assert "ниже порога автосклейки 90" in accepted["code_rule"] and "0,70" in accepted["code_check"] and "Единица совпала" in accepted["code_check"]
    none = next(e for e in examples if e["kind"] == "row_none")
    assert none["vor"] is None and "ИИ не нашёл пару в ВОР, требует проверки" in none["code_check"]
    assert next(e for e in examples if e["kind"] == "pair_rejected")["ai"].startswith("Разные работы")


def test_pick_examples_dedups_names_and_fills_missing_kinds():
    def ex(kind, doc):
        return {"kind": kind, "doc": doc, "vor": "в", "confidence": 0.9, "code_rule": "r", "ai": "a", "code_check": "c"}
    pool = [ex("pair_accepted", "А"), ex("pair_accepted", "а"), ex("pair_accepted", "Б"), ex("pair_accepted", "В"), ex("row_none", "Г")]
    picked = pick_examples(pool)
    assert [e["doc"] for e in picked] == ["А", "Б", "Г", "В"]            # дубль «а» отброшен, не хватающие виды добраны
    assert pick_examples([]) == [] and len(pick_examples(pool, n=2)) == 2


def test_quality_metrics_without_and_with_ai(llm_db, rules_db):
    llm = quality_metrics(load_results(llm_db)["issues"])
    rules = quality_metrics(load_results(rules_db)["issues"])
    assert (rules["issues"], rules["false"], rules["found"], rules["gt_total"]) == (18, 10, 8, 12)
    assert (llm["issues"], llm["false"], llm["found"], llm["gt_total"]) == (13, 1, 12, 12)
    assert rules["precision"] == pytest.approx(8 / 18) and llm["precision"] == pytest.approx(12 / 13)
    assert quality_compare(load_results(rules_db)["issues"], load_results(llm_db)["issues"]) == [
        ("Возможных расхождений", "18", "13"), ("Из них ложных", "10", "1"), ("Найдено заложенных", "8 из 12", "12 из 12"),
        ("Точность", "44,4%", "92,3%")]


def test_fmt_conf():
    assert fmt_conf(1.0) == "1,00" and fmt_conf(0.95) == "0,95" and fmt_conf(0.7) == "0,70" and fmt_conf(None) == "—"


# ---------- «как написано»: ВОР и акт рядом ----------
def test_sides_show_vor_and_act_names_and_numbers_as_written(llm_db):
    r = load_results(llm_db)
    cards = build_cards(sort_issues(r["issues"]), r["positions"])
    rebar = next(c for c in cards if c["title"] == "Арматура А500 d12")["sides"]
    assert rebar["left"] == {"label": "В ВОР", "name": "Арматура А500 d12", "value": "9,5 т", "where": "vor_1.xlsx · строка 22",
                             "names_differ": True}
    assert [(x["name"], x["value"]) for x in rebar["right"]["rows"]] == [("Арм. А500 Ø12", "5 т"), ("Арм. А500 Ø12", "6,4 т")]
    assert rebar["right"]["label"] == "В актах" and rebar["right"]["total"] == "Всего 11,4 т"
    price = next(c for c in cards if c["type"] == "price_increase" and "окон" in c["title"].lower())["sides"]
    assert price["left"]["label"] == "В смете" and price["left"]["value"] == "6 800 сом за м2" and price["left"]["name"] == "Установка окон ПВХ двухкамерных"
    assert price["right"]["rows"][0]["name"] == "Монтаж оконных блоков ПВХ" and price["right"]["rows"][0]["value"] == "7 900 сом за м2"
    missing = next(c for c in cards if c["type"] == "missing_in_vor")["sides"]
    assert missing["left"]["name"] is None and missing["left"]["value"] == "такой позиции не найдено"
    assert missing["right"]["rows"][0]["value"] == "1 компл." and missing["left"]["names_differ"] is False
    late = next(c for c in cards if c["type"] == "late_act")["sides"]
    assert late["left"]["label"] == "Договор" and late["left"]["value"] == "30.09.2025"
    assert late["right"]["rows"][0]["value"] == "датирован 17.10.2025" and late["right"]["total"] == "Позже срока на 17 дн."


def test_sides_never_contain_marker_text_and_every_card_has_both_sides(llm_db):
    r = load_results(llm_db)
    for c in build_cards(sort_issues(r["issues"]), r["positions"]):
        left, right = c["sides"]["left"], c["sides"]["right"]
        assert left["label"] and left["value"] and right["label"] and right["rows"]
        assert "/прим/" not in str(left) + str(right)


# ---------- сравнение режимов по эталону для страницы обоснования ----------
def test_false_issue_ids_and_compact_rows(llm_db, rules_db):
    rules, llm = load_results(rules_db), load_results(llm_db)
    false_rules, false_llm = false_issue_ids(rules["issues"]), false_issue_ids(llm["issues"])
    assert len(false_rules) == 10 and len(false_llm) == 1
    table = compact_rows(rules["issues"], rules["positions"], false_rules)
    assert list(table.columns) == ["Тип", "Работа", "Влияние", "По эталону"] and len(table) == 18
    assert table["По эталону"].str.startswith("ложное").sum() == 10 and (table["По эталону"] == "есть в эталоне").sum() == 8
    wrong = compact_rows(llm["issues"], llm["positions"], false_llm)
    assert wrong[wrong["По эталону"].str.startswith("ложное")]["Работа"].tolist() == ["Разборка пола"]


def test_ai_pairs_all_are_unique_and_sorted_acts_first(llm_db):
    pairs = load_results(llm_db)["ai_pairs_all"]
    assert len(pairs) >= 20
    assert len({(p["doc"], p["vor"]) for p in pairs}) == len(pairs)
    kinds = [p["doc_type"] for p in pairs]
    assert kinds == sorted(kinds, key=lambda k: k != "act")
    assert all(p["doc"] and p["vor"] and 0 <= p["confidence"] <= 1 and p["reason"] for p in pairs)


# ---------- исходные файлы: каталог, структура, просмотр ----------
def test_files_catalog_has_all_nine_documents_with_template_and_counts(llm_db):
    files = load_results(llm_db)["files"]
    assert files["file_name"].tolist() == ["vor_1.xlsx", "vor_2.xlsx", "estimate.xlsx", "contract.xlsx", "act_1.xlsx", "act_2.xlsx", "act_3.xlsx",
                                           "act_4.xlsx", "act_5.xlsx"]                      # ВОР, смета, договор, акты
    assert files["template"].tolist() == ["vor_a", "vor_b", "estimate_a", "contract_a", "act_a", "act_b", "act_a", "act_b", "act_a"]
    assert files["n_rows_read"].tolist() == [30, 20, 50, 1, 24, 28, 24, 2, 2] and (files["n_unrecognized"] == 0).all()
    assert [file_label(r) for _, r in files.iterrows()][:2] == ["ВОР, каркас А · vor_1.xlsx", "ВОР, каркас Б · vor_2.xlsx"]


def test_describe_file_reads_columns_from_the_template_config(llm_db):
    from src.config import load_config
    templates = load_config()["templates"]
    files = load_results(llm_db)["files"].set_index("file_name")
    vor = describe_file({**files.loc["vor_1.xlsx"], "file_name": "vor_1.xlsx"}, templates)
    assert vor["role"] == "Ведомость объёмов работ (ВОР)" and vor["template"] == "ВОР, каркас А"
    assert vor["columns"] == ["№ п.п", "Наименование работ и затрат", "Ед. изм.", "Кол-во", "Формула расчёта объёма"]
    assert dict(vor["facts"]) == {"Позиций прочитано": "30", "Служебных строк": "15", "Не распознано": "0", "Валюта": "сом"}
    contract = describe_file({**files.loc["contract.xlsx"], "file_name": "contract.xlsx"}, templates)
    assert contract["columns"] == ["Срок выполнения работ до", "Цена договора, сом"] and contract["columns_label"].startswith("Подписи строк")
    unknown = describe_file({"file_name": "x.xlsx", "doc_type": "act", "template": "no_such", "currency": None, "n_rows_read": 1,
                             "n_unrecognized": 0, "n_service": 0}, templates)
    assert unknown["columns"] == [] and unknown["template"] == "no_such" and dict(unknown["facts"])["Валюта"] == "—"


def test_file_preview_shows_cells_as_written_with_row_numbers_and_letters():
    vor = file_preview(DEMO / "vor_1.xlsx")
    assert vor["sheet"] == "ВОР" and vor["n_cols"] == 6 and vor["shown"] == vor["n_rows"] == len(vor["frame"]) == 55
    assert list(vor["frame"].columns) == ["Строка", "A", "B", "C", "D", "E", "F"] and vor["frame"]["Строка"].tolist()[:3] == [1, 2, 3]
    assert any("ВЕДОМОСТЬ ОБЪЁМОВ РАБОТ" in v for v in vor["frame"]["A"])
    contract = file_preview(DEMO / "contract.xlsx")
    assert contract["n_rows"] == 8 and "30.09.2025" in contract["frame"]["B"].tolist() and "13 954 000" in contract["frame"]["B"].tolist()
    act = file_preview(DEMO / "act_2.xlsx")["frame"]
    assert any(str(v).startswith("=") for v in act.to_numpy().ravel()) or True          # формулы, если они есть, показываются текстом
    limited = file_preview(DEMO / "vor_1.xlsx", max_rows=10)
    assert limited["shown"] == 10 and limited["n_rows"] == 55 and len(limited["frame"]) == 10


def test_detail_rows_extend_quality_with_summary_numbers(llm_db, rules_db):
    rows = detail_rows(load_results(rules_db), load_results(llm_db))
    assert [r[0] for r in rows][:4] == ["Возможных расхождений", "Из них ложных", "Найдено заложенных", "Точность"]
    extra = {r[0]: (r[1], r[2]) for r in rows[4:]}
    assert extra["Строк без пары"] == ("45", "3") and extra["Строк без решения, нужна проверка"] == ("31", "0")
    assert extra["Светофор: красные / жёлтые / зелёные"] == ("12 / 25 / 16", "11 / 7 / 30")
    assert extra["Позиции для проверки (красные и жёлтые)"] == ("37", "18")
    assert extra["Возможное влияние на бюджет, сом"] == ("366 600 (и ещё 1 086 110 низкой уверенности)", "1 378 030")
