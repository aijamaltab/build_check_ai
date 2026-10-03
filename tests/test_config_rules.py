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
    assert m["summary_template"].format(n=1, m=2) == "проверено 1 позиций, не сопоставлено 2"
    assert m["kind_unknown_dq_check"] == "kind не определён"


def test_evaluate_modes_and_metrics():
    ev = RULES["evaluate"]
    assert ev["modes"] == ["no_synonyms", "synonyms", "synonyms_llm"]
    assert "false_unmatched" in ev["metrics"]
    assert ev["false_unmatched_list_fields"] == ["file", "sheet", "row"]


def test_synonyms_file_starts_with_rule_block():
    head = [line for line in SYNONYMS_TEXT.splitlines()[:15]]
    assert all(line.startswith("#") or not line for line in head)
    block = "\n".join(head)
    assert "ПРАВИЛО ПОПОЛНЕНИЯ СЛОВАРЯ" in block
    assert "РЕАЛЬНЫХ" in block and "откуда" in block
    assert "generate_synthetic.py" in block


def test_spec_describes_unmatched_rows_and_metric():
    for phrase in ("### Строка без пары", "«не сопоставлена»", "missing_in_vor",
                   "проверено N позиций, не сопоставлено M", "ложные не сопоставленные",
                   "### Правило пополнения `synonyms.yaml`"):
        assert phrase in SPEC, phrase
