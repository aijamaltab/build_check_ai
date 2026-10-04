"""scripts/run_all.py: сквозной сценарий в консоли."""
import importlib.util
import sys
from pathlib import Path

import pytest

from src.config import load_config
from tests.test_generate_synthetic import gen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("run_all", ROOT / "scripts" / "run_all.py")
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)
CFG = load_config()


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic")
    gen.generate(out_dir=out, meta_dir=out)
    return out


def run(source, tmp_path, capsys, *args):
    assert ra.main(["--source", str(source), "--db", str(tmp_path / "r.db"), *args]) == 0
    return capsys.readouterr().out


def test_rules_only_prints_banner_summary_issues_and_disclaimer(source, tmp_path, capsys):
    out = run(source, tmp_path, capsys)
    assert CFG["rules"]["llm"]["rules_only_banner"] in out and "режим rules_only" in out
    assert "Проверено 180 позиций" in out and "Позиции по светофору" in out and "низкая уверенность" in out
    assert "Светофор ориентировочный".lower() in out.lower() and "окончательное решение за специалистом" in out
    assert "act_2.xlsx:Акт:" in out and "Возможное расхождение" in out and "нарушен" not in out.lower()


def test_llm_with_fake_judges_is_marked_as_ceiling_and_finds_12(source, tmp_path, capsys):
    out = run(source, tmp_path, capsys, "--mode", "llm", "--ai-ceiling")
    assert "потолок" in out and "расхождений 12" in out and "режим llm" in out
    assert "красных 10, жёлтых 6, зелёных 31" in out and "[низкая уверенность]" not in out
    assert "ИИ не нашёл пару" in out


def test_llm_without_judges_is_not_substituted_silently(source, tmp_path, capsys):
    out = run(source, tmp_path, capsys, "--mode", "llm")
    assert "(запрошен режим llm)" in out and "режим rules_only" in out


def test_decimal_comma_in_explanations(source, tmp_path, capsys):
    out = run(source, tmp_path, capsys, "--mode", "llm", "--ai-ceiling")
    assert "больше на 33,3 %" in out
