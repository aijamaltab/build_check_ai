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
    assert m["summary_template"].format(n=1, m=2, k=3, l=4) == (
        "Проверено 1 позиций, не распознано 2, не сопоставлено 3, не сопоставимо 4")
    assert m["kind_unknown_dq_check"] == "kind не определён"


def test_evaluate_modes_and_metrics():
    ev = RULES["evaluate"]
    assert ev["modes"] == ["no_synonyms", "synonyms", "synonyms_llm"]
    assert ev["thresholds"] == [85, 90]
    assert "false_unmatched" in ev["metrics"] and "false_merges" in ev["metrics"]
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
                   "Проверено N позиций, не распознано M, не сопоставлено K, не сопоставимо L", "ложные не сопоставленные",
                   "### Правило пополнения `synonyms.yaml`"):
        assert phrase in SPEC, phrase


def test_summary_line_and_backlog_in_docs():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Проверено N позиций, не распознано M, не сопоставлено K, не сопоставимо L" in claude
    assert "два образца реального акта, не с портала, один акт, выводов про все акты нет" in claude
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    assert "Работа есть в смете, но нет в ВОР" in backlog


# ---------- образцы реального акта: шаблон act_c, порог 90, валюта, цена по ключу ----------
TEMPLATES = yaml.safe_load((ROOT / "config" / "templates.yaml").read_text(encoding="utf-8"))["templates"]

ACT_C_KEYS = ["header_keywords", "header_by_row_number", "date_cell_above_header", "object_name_row_without_number",
              "currency_from_header_text", "ignore_unnamed_columns", "price_is_formula",
              "percent_in_note", "allow_repeated_names"]


def test_act_c_template_has_required_keys():
    act_c = TEMPLATES["act_c"]
    assert act_c["doc_type"] == "act"
    for key in ACT_C_KEYS:
        assert key in act_c, key
    assert "header_search" not in act_c
    assert act_c["header_by_row_number"] is False
    assert isinstance(act_c["header_keywords"], list)          # тот же формат, что у остальных шаблонов
    assert {"наименование", "единица измерения"} <= set(act_c["header_keywords"])
    assert all(isinstance(t["header_keywords"], list) for t in TEMPLATES.values() if "header_keywords" in t)
    assert act_c["date_cell_above_header"] is True and act_c["price_is_formula"] is True
    assert re.search(act_c["currency_from_header_text"]["pattern"], "Цена за единицу (USD)")


def test_rules_threshold_90_must_match_tokens_currency_and_formulas():
    m = RULES["matching"]
    assert m["fuzzy_threshold"] == 90 and m["llm_lower_bound"] == 60
    assert m["must_match_tokens"]["exclusive_word_groups"] == [["внутренн", "наружн"]]
    assert m["must_match_tokens"]["bracket_text"] == "must_equal"
    assert len(m["must_match_tokens"]["patterns"]) == 4
    assert RULES["price_increase"]["price_basis"] == "weighted_by_key"
    assert RULES["price_increase"]["formula_price_note"]
    assert RULES["volume_exceeded"]["explanation_if_price_is_formula"]
    cur = RULES["currency"]
    assert cur["convert"] is False and cur["mismatch_policy"] == "skip_price_and_amount_checks"
    assert cur["mismatch_dq_check"] == "валюты не совпадают" and cur["mismatch_summary_label"] == "не сопоставимо"
    f = RULES["formulas"]
    assert f["read_mode"] == "data_only" and f["missing_value_dq_check"] == "формула без значения"


def test_must_match_tokens_single_source_is_rules_yaml():
    synonyms = yaml.safe_load(SYNONYMS_TEXT)
    assert "must_match_tokens" not in synonyms
    assert "config/rules.yaml, matching.must_match_tokens" in SYNONYMS_TEXT.replace("\n# ", " ")


def must_match_ok(a: str, b: str) -> bool:
    """Прототип правила matching.must_match_tokens из rules.yaml (токены, слова группы, текст в скобках)."""
    cfg = RULES["matching"]["must_match_tokens"]
    for pattern in cfg["patterns"]:
        if re.findall(pattern, a.lower()) != re.findall(pattern, b.lower()):
            return False
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
    """Тест-кейс matching (нейтральная вымышленная пара): отличается одним словом, token_set_ratio около 85."""
    a, b = "Внутренняя перегородка (гипсокартон)", "Наружная перегородка (гипсокартон)"
    raw = fuzz.token_set_ratio(a, b)
    lowered = fuzz.token_set_ratio(a.lower(), b.lower())
    m = RULES["matching"]
    assert int(raw) == 84                                   # 84,7 на исходных строках
    assert int(lowered) == 85                               # 85,7 после lower(), как в нашем пайплайне
    assert m["llm_lower_bound"] <= raw < m["fuzzy_threshold"]
    assert m["llm_lower_bound"] <= lowered < m["fuzzy_threshold"]
    assert not must_match_ok(a, b) and must_match_ok(a, a)
    # без LLM пара не сливается: ни по порогу 90, ни по обязательным токенам
    assert not (lowered >= m["fuzzy_threshold"] and must_match_ok(a, b))
    # при пороге 85 по оценке она слилась бы (это то, что сравнит evaluate.py)
    assert lowered >= min(RULES["evaluate"]["thresholds"])


def test_must_match_patterns_keep_diameters_apart():
    assert not must_match_ok("Арматура А500 d12", "Арматура А240 d8")
    assert must_match_ok("Арматура А500 d12", "Арматура А500 d12")


def test_bracket_text_must_equal():
    assert not must_match_ok("Труба (изолированная)", "Труба (неизолированная)")
    assert must_match_ok("Труба (изолированная)", "Труба (изолированная)")


def test_spec_has_currency_weighted_price_and_formula_rules():
    for phrase in ("средневзвешенная цена", "валюты не совпадают", "не сопоставимо", "Валюты не конвертируем",
                   "формула без значения", "data_only=True", "количество могло быть выведено из суммы",
                   "### Валюта", "### Цена по ключу и формулы", "`fuzzy_threshold` равен **90**",
                   "**единственный источник**", "`fuzzy_threshold` 85 и 90", "ложных склеек",
                   "порог выбирается на синтетике", "Внутренняя перегородка (гипсокартон)"):
        assert phrase in SPEC, phrase


def test_schema_proposal_and_backlog_mention_currency():
    proposal = (ROOT / "docs" / "schema_change_proposal.md").read_text(encoding="utf-8")
    assert "documents.currency" in proposal and "## 4." in proposal
    for old in ("quantity_raw", "contractor", "items.kind", "`kind`"):
        assert old in proposal
    backlog = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
    for phrase in ("Конвертация валют", "круглую сумму", "Генератор шаблона акта В"):
        assert phrase in backlog


# ---------- ИИ как основа продукта: блок llm, фразы в документах (CLAUDE.md §3, spec §10) ----------
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
BACKLOG = (ROOT / "docs" / "backlog.md").read_text(encoding="utf-8")
LLM_KEYS = ["model", "temperature", "cache_dir", "schema_version", "max_retries", "timeout", "modes", "functions"]


def test_rules_have_llm_block_with_required_keys():
    llm = RULES["llm"]
    for key in LLM_KEYS:
        assert key in llm, key
    assert llm["temperature"] == 0
    assert llm["modes"] == ["llm", "rules_only"] and llm["default_mode"] == "llm"
    assert set(llm["functions"]) == {"matching", "row_matching", "template_reading", "explanations", "report"}
    assert all(isinstance(v, bool) for v in llm["functions"].values())
    assert llm["max_retries"] >= 0 and llm["timeout"] > 0 and llm["schema_version"]
    assert llm["cache_dir"].startswith("data/cache")
    assert 0 < llm["min_confidence"] < 1 and llm["rules_only_banner"]


def test_llm_block_marks_model_and_limits_for_checking_and_has_no_secret():
    text = (ROOT / "config" / "rules.yaml").read_text(encoding="utf-8")
    block = text[text.index("\nllm:"):text.index("# Режимы evaluate.py")]
    assert block.count("проверить на сегодняшнюю дату") >= 2          # модель и лимиты
    assert "AIza" not in text                                            # ключи Google API начинаются так
    assert RULES["llm"]["api_key_env"].isupper() and "KEY" in RULES["llm"]["api_key_env"]   # только имя переменной


def test_llm_modes_match_runs_table_and_matching_skip_mode():
    from src.db import SCHEMA
    for mode in RULES["llm"]["modes"]:
        assert f"'{mode}'" in SCHEMA                                     # те же значения, что runs.mode
    assert RULES["matching"]["skip_llm_in_modes"] == ["rules_only"]
    assert RULES["llm"]["cache_dir"] == "data/cache/llm"


def test_spec_has_ai_functions_section():
    for phrase in ("## 10. ИИ-функции", "LLM никогда не считает числа", "режим `rules_only`", "режиме `llm`",
                   "Функция «а»", "Функция «б»", "Функция «в»", "same_work", "confidence", "reason",
                   "`matches`", "`method = llm`", "первые 20 строк", "header_row", "column_mapping", "section_rows",
                   "total_rows", "currency", "Вход только из таблицы `issues`", "Числа **берутся из таблицы",
                   "Температура 0", "Кэш по хешу запроса", "`data/cache/llm/`", "Проверка схемы JSON",
                   "Ключ только из переменных окружения", "Разбор одного PDF через Gemini",
                   "Чат по отчёту"):
        assert phrase in SPEC, phrase


def test_spec_evaluate_has_pitch_table_without_ai_and_with_ai():
    for phrase in ("### Итоговая таблица для питча «без ИИ / с ИИ»", "`no_synonyms`", "`synonyms`", "`synonyms_llm`",
                   "Найдено из 12", "Ложные срабатывания", "Ложные «не сопоставлено»",
                   "словарь и `must_match_tokens` составлены по тем же названиям"):
        assert phrase in SPEC, phrase


def test_claude_md_states_ai_principle_scope_and_definition_of_done():
    assert "ИИ читает, понимает и объясняет; обычный код считает и проверяет" in CLAUDE
    assert "LLM никогда не считает числа" in CLAUDE
    assert "`rules_only`" in CLAUDE and "ИИ-режим недоступен, использован базовый режим" in CLAUDE
    assert "необязательный слой" not in CLAUDE                         # старая формулировка убрана
    assert "ИИ-функции видны в демо; `evaluate.py` сравнивает режимы без ИИ и с ИИ" in CLAUDE
    freeze = CLAUDE[CLAUDE.index("## 4. Заморозка"):CLAUDE.index("## 5. Стек")]
    for phrase in ("ИИ-сопоставление спорных пар", "ИИ-чтение незнакомого шаблона Excel", "ИИ-объяснения красных расхождений"):
        assert phrase in freeze, phrase
    assert "Требование ментора" in CLAUDE[CLAUDE.index("## 1. "):CLAUDE.index("## 2. ")]


def test_backlog_has_ai_ideas_and_no_chat():
    for phrase in ("Разбор PDF через Gemini", "Живой запуск на новом файле во время питча",
                   "Чат по отчёту (НЕ делаем)", "ChatGPT для X"):
        assert phrase in BACKLOG, phrase
    assert "ChatGPT для X" in SPEC or "ChatGPT для X" in CLAUDE


# ---------- состояния строки, правило «подмножество», сходство названий, RowMatcher ----------
def test_rules_have_states_subset_and_similarity_keys():
    m = RULES["matching"]
    assert m["states"] == ["matched", "ambiguous", "absent"] and m["unmatched_issue_only_state"] == "absent"
    assert m["ambiguous_dq_check"] and "{a}" in m["summary_with_review_template"]
    assert "{k}" in m["summary_template"] and "{a}" not in m["summary_template"]        # старый шаблон сводки не менялся
    assert 0 < m["subset_review_below"] <= 100 and m["subset_review_scope"] in ("always", "competitor")
    assert m["name_similarity"] in ("plain", "stemmed") and m["stem_endings"] and m["stem_min_len"] >= 1
    assert isinstance(m["competitor_review"], bool) and "монтаж" in m["candidate_ignore_words"]
    assert m["must_match_tokens"]["missing_side"] in ("block", "allow") and m["must_match_tokens"]["llm_veto"] == ["patterns"]
    assert "stop_words" not in m                                                           # стоп-слов нет (synonyms.yaml)
    assert RULES["llm"]["functions"]["row_matching"] is True


def test_spec_describes_states_similarity_and_row_matcher():
    for phrase in ("`ambiguous`", "`absent`", "Только `absent`", "Правило «подмножество»", "### Сходство названий",
                   "Стоп-слов нет", "Функция «а2»", "RowMatcher", "staging_llm_row_decisions", "ложные `absent`",
                   "Многосигнальный скоринг", "не внесён", "`staging_match_rows.state`", "summary_with_review_template"):
        assert phrase in SPEC, phrase
    assert "пять строк акта №3 (позиции №10, 19, 20, 31, 35) остаются ложными" not in SPEC    # неверное ожидание убрано


# ---------- проверки, issues, evaluate: тексты и пороги в конфиге, фразы в спецификации ----------
def test_rules_have_issue_texts_severity_and_summary_template():
    i = RULES["issues"]
    assert set(i["explanations"]) >= {"volume_exceeded", "price_increase", "missing_in_vor", "late_act"}
    for text in i["explanations"].values():
        assert not any(bad in text.lower() for bad in ("нарушен", "мошенн", "хищен"))
    for key in ("volume_exceeded", "price_increase", "missing_in_vor", "late_act"):
        assert "Возможное расхождение" in i["explanations"][key] and "Требует проверки" in i["explanations"][key]
    assert i["missing_in_vor"]["severity_unconfirmed"] != "high" and i["missing_in_vor"]["severity_confirmed"] == "high"
    assert "Без ИИ" in i["missing_in_vor"]["low_confidence_note"] and "{a}" in i["rules_only_status_caveat"]
    assert all(f"{{{k}}}" in i["summary_run_template"] for k in ("n", "m", "k", "a", "l", "z", "impact", "mode"))
    assert RULES["late_act"]["severity"] in RULES["severity_levels"] and i["severity_default"] in RULES["severity_levels"]


def test_spec_describes_issue_storage_views_and_evaluate_results():
    for phrase in ("`staging_issues_ext`", "**лист** (в `issues` его нет)", "`review_rows`", "Без ИИ, низкая уверенность, требует проверки",
                   "потолок, не оценка модели", "Какие GT не найдены без ИИ и почему", "Полнота `missing_in_vor`",
                   "(низкой уверенности)", "Ловушки не сработали", "run_pipeline", "ориентировочный"):
        assert phrase in SPEC, phrase
    assert "Значения подставляет прогон, до него в таблице нет цифр" not in SPEC           # таблица заполнена результатами прогона
