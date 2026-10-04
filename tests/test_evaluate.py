"""scripts/evaluate.py: правила подсчёта на маленьком наборе и сквозной прогон на синтетике."""
import importlib.util
import sys
from pathlib import Path

import pytest

from src.config import load_config
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("evaluate", ROOT / "scripts" / "evaluate.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
CFG = load_config()


def issue(t, file, row, sheet="Акт", conf="high"):
    return {"issue_type": t, "source_file": file, "source_sheet": sheet, "source_row": row, "confidence": conf, "work_key": "k"}


GT = [
    {"gt_id": "1", "issue_type": "volume_exceeded", "source_file": "act_3.xlsx", "canonical_name": "Бетон",
     "related_rows": "vor_1.xlsx:ВОР:19;estimate.xlsx:Смета:23;act_2.xlsx:Акт:10;act_3.xlsx:Акт:7"},
    {"gt_id": "9", "issue_type": "missing_in_vor", "source_file": "act_3.xlsx", "canonical_name": "Отмостка",
     "related_rows": "act_3.xlsx:Акт:33"},
    {"gt_id": "11", "issue_type": "late_act", "source_file": "act_4.xlsx", "canonical_name": "Акт №4", "related_rows": "act_4.xlsx:Акт:2"},
    {"gt_id": "12", "issue_type": "late_act", "source_file": "act_5.xlsx", "canonical_name": "Акт №5", "related_rows": "act_5.xlsx:Акт:2"},
]
TRAPS = [{"trap_id": "1", "item_no": "17", "related_rows": "act_1.xlsx:Акт:28;act_2.xlsx:Акт:18", "description": "объём +3%"},
         {"trap_id": "2", "item_no": "32", "related_rows": "act_2.xlsx:Акт:31", "description": "цена +2%"}]


def test_gt_found_by_type_and_row_in_related_rows():
    r = ev.evaluate_issues([issue("volume_exceeded", "act_2.xlsx", 10)], GT, TRAPS)       # любая строка из related_rows подходит
    assert r["found_ids"] == ["1"] and r["found"] == 1 and r["gt_total"] == 4


def test_wrong_type_or_wrong_sheet_or_wrong_row_is_not_a_hit():
    for bad in (issue("price_increase", "act_2.xlsx", 10), issue("volume_exceeded", "act_2.xlsx", 10, sheet="Другой"),
                issue("volume_exceeded", "act_2.xlsx", 11)):
        assert ev.evaluate_issues([bad], GT, TRAPS)["found"] == 0


def test_several_issues_for_one_gt_are_one_hit_and_none_is_false():
    issues = [issue("volume_exceeded", "act_2.xlsx", 10), issue("volume_exceeded", "act_3.xlsx", 7)]
    r = ev.evaluate_issues(issues, GT, TRAPS)
    assert r["found"] == 1 and r["false_count"] == 0 and r["precision"] == 1.0 and r["true_issues"] == 2


def test_late_act_matches_by_type_and_act_file_only():
    r = ev.evaluate_issues([issue("late_act", "act_4.xlsx", 99)], GT, TRAPS)               # строка не важна, важен файл акта
    assert r["found_ids"] == ["11"]
    assert ev.evaluate_issues([issue("late_act", "act_1.xlsx", 2)], GT, TRAPS)["found"] == 0


def test_false_positive_precision_and_missing_recall():
    issues = [issue("missing_in_vor", "act_3.xlsx", 33, conf="low"), issue("missing_in_vor", "act_2.xlsx", 8, conf="low"),
              issue("volume_exceeded", "act_1.xlsx", 5)]
    r = ev.evaluate_issues(issues, GT, TRAPS)
    assert (r["found"], r["false_count"], r["false_low_confidence"]) == (1, 2, 1)
    assert r["precision"] == pytest.approx(1 / 3) and (r["missing_found"], r["missing_total"]) == (1, 1)
    assert r["recall"] == 0.25


def test_traps_are_counted_separately():
    r = ev.evaluate_issues([issue("volume_exceeded", "act_1.xlsx", 28), issue("late_act", "act_4.xlsx", 2)], GT, TRAPS)
    assert r["traps_triggered"] == 1 and [t["triggered"] for t in r["traps"]] == [True, False]
    assert r["false_count"] == 1                                                            # issue на ловушке это и ложное срабатывание


def test_no_issues_gives_no_precision():
    r = ev.evaluate_issues([], GT, TRAPS)
    assert r["precision"] is None and r["found"] == 0 and r["traps_triggered"] == 0


# ---------- сквозной прогон на синтетике ----------
@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    generated = gen.generate(out_dir=out, meta_dir=out)
    return {"dir": out, "truth": {(r["file"], r["row"]): r["item_no"] for r in generated.log},
            "gt": ev.read_csv(out / "ground_truth.csv"), "traps": ev.read_csv(out / "traps.csv")}


def go(synth, mode, threshold, tmp_path, ceiling=True):
    return ev.run_config(synth["dir"], synth["gt"], synth["traps"], CFG, synth["truth"], mode, threshold, ceiling, tmp_path)


def test_ai_ceiling_finds_all_12_without_false_issues_or_traps(synth, tmp_path):
    for th in (85, 90):
        r = go(synth, "synonyms_llm", th, tmp_path)
        assert (r["found"], r["gt_total"], r["false_count"], r["traps_triggered"]) == (12, 12, 0, 0)
        assert (r["missing_found"], r["missing_total"]) == (2, 2) and r["precision"] == 1.0
        assert r["false_unmatched"] == 0 and r["false_merges"] == 0


def test_llm_mode_is_skipped_not_replaced_without_ai(synth, tmp_path):
    assert go(synth, "synonyms_llm", 90, tmp_path, ceiling=False) is None
    table = ev.slide_table({("synonyms_llm", 90): None}, [90])
    assert "пропущен: реальный ИИ не подключён" in table


def test_rules_only_finds_less_and_explains_what_it_missed(synth, tmp_path):
    ai = go(synth, "synonyms_llm", 90, tmp_path)
    plain = go(synth, "synonyms", 90, tmp_path)
    nosyn = go(synth, "no_synonyms", 90, tmp_path)
    assert nosyn["found"] <= plain["found"] < ai["found"] == 12
    assert plain["false_count"] > 0 and plain["false_low_confidence"] == plain["false_count"]    # все ложные без ИИ: низкая уверенность
    assert plain["traps_triggered"] == 0 and plain["false_merges"] == 0
    assert (plain["missing_found"], plain["missing_total"]) == (2, 2)
    assert {"11", "12"} <= set(plain["found_ids"])                                           # late_act не зависит от сопоставления
    # у каждого ненайденного GT есть объяснение со строками и их состояниями
    assert len(plain["not_found_why"]) == 12 - plain["found"] > 0
    assert all("состояния:" in why for _, _, _, why in plain["not_found_why"])
    assert any("ambiguous" in why for *_, why in plain["not_found_why"])


def test_slide_table_has_all_columns_and_modes(synth, tmp_path):
    results = {(m, 90): go(synth, m, 90, tmp_path) for m in ("no_synonyms", "synonyms", "synonyms_llm")}
    table = ev.slide_table(results, [90])
    for phrase in ("без ИИ, без словаря", "без ИИ, со словарём", "с ИИ (потолок, не оценка модели)", "12 из 12", "из 12",
                   "Ложные срабатывания", "Полнота missing_in_vor", "Ложные «не сопоставлено»", "Ловушки сработали"):
        assert phrase in table, phrase


def test_main_prints_table_and_honesty_note(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["evaluate.py", "--ai-ceiling"])
    assert ev.main() == 0
    out = capsys.readouterr().out
    assert "цифры оптимистичны" in out and "потолок" in out and "Итоговая таблица для слайда" in out
    assert "Какие GT не найдены и почему" in out
