"""Проверки конфигов и спецификации: правила обработки строк без пары (docs/synthetic_spec.md §6 и §8)."""
import re
from pathlib import Path

import yaml
from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
RULES = yaml.safe_load((ROOT / "config" / "rules.yaml").read_text(encoding="utf-8"))
SPEC = (ROOT / "docs" / "synthetic_spec.md").read_text(encoding="utf-8")
SYNONYMS_TEXT = (ROOT / "config" / "synonyms.yaml").read_text(encoding="utf-8")


def test_rules_have_matching_order_params():
    m = RULES["matching"]
    assert m["pipeline"] == ["synonyms", "rapidfuzz", "llm"]
    assert m["llm_zone"] == ["llm_lower_bound", "fuzzy_threshold"]
    assert all(name in m for name in m["llm_zone"])
    assert m["llm_lower_bound"] < m["fuzzy_threshold"]
    assert m["skip_llm_in_modes"] == ["rules_only"]
    assert m["rules_only_explanation"]
    assert m["unmatched_status"] == "не сопоставлена"
    assert m["unmatched_issue"] == {"document": "act", "issue_type": "missing_in_vor"}
    assert m["summary_template"].format(n=1, m=2, k=3) == "Проверено 1 позиций, не распознано 2, не сопоставлено 3"
    assert m["kind_unknown_dq_check"] == "kind не определён"


def test_evaluate_modes_and_metrics():
    ev = RULES["evaluate"]
    assert ev["modes"] == ["no_synonyms", "synonyms", "synonyms_llm"]
    assert "false_unmatched" in ev["metrics"]
    assert ev["false_unmatched_list_fields"] == ["file", "sheet", "row"]


def test_synonyms_file_starts_with_rule_block():
    head = []
    for line in SYNONYMS_TEXT.splitlines():
        if not line.startswith("#"):
            break
        head.append(line)
    block = "\n".join(head)
    assert "ПРАВИЛО ПОПОЛНЕНИЯ СЛОВАРЯ" in block
    assert "РЕАЛЬНЫХ" in block and "откуда" in block
    assert "generate_synthetic.py" in block
    assert "источник не подтверждён" in block and "07.10" in block


def test_every_synonym_entry_has_source_comment():
    """Правило: у каждой записи synonyms и abbreviations есть комментарий «откуда»."""
    section, checked = None, 0
    for line in SYNONYMS_TEXT.splitlines():
        if line.startswith(("synonyms:", "abbreviations:")):
            section = line.split(":")[0]
            continue
        if line and not line.startswith((" ", "#")):
            section = None
        if section and line.startswith("  ") and line.strip():
            assert "откуда" in line, line
            checked += 1
    assert checked >= 20


def test_spec_describes_unmatched_rows_and_metric():
    for phrase in ("### Строка без пары", "«не сопоставлена»", "missing_in_vor",
                   "Проверено N позиций, не распознано M, не сопоставлено K", "ложные не сопоставленные",
                   "### Правило пополнения `synonyms.yaml`"):
        assert phrase in SPEC, phrase


def test_summary_line_and_backlog_in_docs():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Проверено N позиций, не распознано M, не сопоставлено K" in claude
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    assert "Работа есть в смете, но нет в ВОР" in backlog


# ---------- образцы реального акта: шаблон act_c, порог 90, валюта, цена по ключу ----------
TEMPLATES = yaml.safe_load((ROOT / "config" / "templates.yaml").read_text(encoding="utf-8"))["templates"]

ACT_C_KEYS = ["header_search", "date_cell_above_header", "object_name_row_without_number",
              "currency_from_header_text", "ignore_unnamed_columns", "price_is_formula",
              "percent_in_note", "allow_repeated_names"]


def test_act_c_template_has_required_keys():
    act_c = TEMPLATES["act_c"]
    assert act_c["doc_type"] == "act"
    for key in ACT_C_KEYS:
        assert key in act_c, key
    assert act_c["header_search"]["by_row_number"] is False
    assert {"наименование", "единица измерения"} <= set(act_c["header_search"]["keywords"])
    assert act_c["date_cell_above_header"] is True and act_c["price_is_formula"] is True
    assert re.search(act_c["currency_from_header_text"]["pattern"], "Цена за единицу (USD)")


def test_rules_threshold_90_must_match_tokens_currency_and_formulas():
    m = RULES["matching"]
    assert m["fuzzy_threshold"] == 90 and m["llm_lower_bound"] == 60
    assert m["must_match_tokens"]["exclusive_word_groups"] == [["внутренний", "наружный"]]
    assert m["must_match_tokens"]["bracket_text"] == "must_equal"
    assert RULES["price_increase"]["price_basis"] == "weighted_by_key"
    assert RULES["price_increase"]["formula_price_note"]
    assert RULES["volume_exceeded"]["explanation_if_price_is_formula"]
    cur = RULES["currency"]
    assert cur["convert"] is False and cur["mismatch_policy"] == "skip_price_and_amount_checks"
    assert cur["mismatch_dq_check"] == "валюты не совпадают" and cur["mismatch_summary_label"] == "не сопоставимо"
    f = RULES["formulas"]
    assert f["read_mode"] == "data_only" and f["missing_value_dq_check"] == "формула без значения"


def must_match_ok(a: str, b: str) -> bool:
    """Прототип правила matching.must_match_tokens из rules.yaml (слова группы и текст в скобках)."""
    cfg = RULES["matching"]["must_match_tokens"]
    for group in cfg["exclusive_word_groups"]:
        wa = {w for w in group if w in a.lower()}
        wb = {w for w in group if w in b.lower()}
        if wa != wb:
            return False
    if cfg["bracket_text"] == "must_equal":
        ba, bb = re.findall(r"\(([^)]*)\)", a.lower()), re.findall(r"\(([^)]*)\)", b.lower())
        if ba != bb:
            return False
    return True


def test_similar_names_with_different_word_are_not_one_work():
    """Тест-кейс matching: пара отличается одним словом, token_set_ratio около 85, это разные работы."""
    a, b = "Внутренний желоб (закрывающий настил)", "Наружный желоб (закрывающий настил)"
    raw = fuzz.token_set_ratio(a, b)
    lowered = fuzz.token_set_ratio(a.lower(), b.lower())
    m = RULES["matching"]
    assert int(raw) == 85                                   # 85,2 на исходных строках
    assert m["llm_lower_bound"] <= raw < m["fuzzy_threshold"]
    assert m["llm_lower_bound"] <= lowered < m["fuzzy_threshold"]   # 86,1 после lower()
    assert not must_match_ok(a, b) and must_match_ok(a, a)
    # без LLM пара не сливается: ни по порогу, ни по обязательным токенам
    assert not (raw >= m["fuzzy_threshold"] and must_match_ok(a, b))
    # со старым порогом 85 пара слилась бы
    assert raw >= 85


def test_bracket_text_must_equal():
    assert not must_match_ok("Труба (изолированная)", "Труба (неизолированная)")
    assert must_match_ok("Труба (изолированная)", "Труба (изолированная)")


def test_spec_has_currency_weighted_price_and_formula_rules():
    for phrase in ("средневзвешенная цена", "валюты не совпадают", "не сопоставимо", "Валюты не конвертируем",
                   "формула без значения", "data_only=True", "количество могло быть выведено из суммы",
                   "### Валюта", "### Цена по ключу и формулы", "`fuzzy_threshold` равен **90**"):
        assert phrase in SPEC, phrase


def test_schema_proposal_and_backlog_mention_currency():
    proposal = (ROOT / "docs" / "schema_change_proposal.md").read_text(encoding="utf-8")
    assert "documents.currency" in proposal and "## 4." in proposal
    for old in ("quantity_raw", "contractor", "items.kind", "`kind`"):
        assert old in proposal
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    for phrase in ("Конвертация валют", "круглую сумму", "Генератор шаблона акта В"):
        assert phrase in backlog
