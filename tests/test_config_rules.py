"""Проверки конфигов и спецификации: правила обработки строк без пары (docs/synthetic_spec.md §6 и §8)."""
from pathlib import Path

import yaml

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
