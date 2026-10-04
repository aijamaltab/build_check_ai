"""Демо в режиме llm воспроизводится из закоммиченного кэша data/cache/llm без ключа и без API.

Тест читает реальный кэш только на чтение (LLM_CACHE_ONLY=1, ключа нет, transport не создаётся); фикстура защиты кэша из conftest
проверяет, что файлы не изменились. Если кэш не закоммичен или устарел (поменялся промт, список ВОР или синтетика), тест падает:
перезапустите scripts/run_llm.py и закоммитьте data/cache/llm/.
"""
import re
import sqlite3
from pathlib import Path

import pytest

from src.config import load_config
from src.pipeline import run_pipeline
from tests.cache_guard import REAL_CACHE

ROOT = Path(__file__).resolve().parents[1]
CFG = load_config()
SECRET_LIKE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
LONG_TOKEN = re.compile(r"[A-Za-z0-9_-]{32,}")
SHA256 = re.compile(r"[0-9a-f]{64}")           # хеш списка ВОР в payload записей row: не секрет


def cache_files():
    return sorted(p for p in REAL_CACHE.glob("*.json") if not p.name.startswith("_"))


@pytest.fixture()
def real_cache_readonly(monkeypatch):
    assert cache_files(), f"в {REAL_CACHE} нет записей кэша: запустите scripts/run_llm.py и закоммитьте кэш"
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))        # перекрывает временную папку из conftest
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_llm_demo_reproduces_from_committed_cache_without_key_or_api(real_cache_readonly, tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import evaluate as ev
    s = run_pipeline(ROOT / "data" / "synthetic", tmp_path / "demo.db", "llm", cfg=CFG)
    assert s["mode"] == "llm" and s["requested_mode"] == "llm" and s["banner"] is None
    ai = s["ai"]
    assert ai["calls"] == 0 and ai["errors"] == 0 and ai["no_answer"] == 0 and ai["stop_reason"] is None
    assert ai["pairs_no_decision"] == 0 and ai["rows_no_decision"] == 0, "кэш неполный для текущих промтов и данных"
    assert ai["cache_hits"] > 0 and s["z"] == 13

    conn = sqlite3.connect(tmp_path / "demo.db")
    conn.row_factory = sqlite3.Row
    issues = [dict(r) for r in conn.execute("SELECT * FROM issues_view")]
    result = ev.evaluate_issues(issues, ev.read_csv(ROOT / "data" / "ground_truth.csv"), ev.read_csv(ROOT / "data" / "traps.csv"))
    assert result["found"] == result["gt_total"] == 12
    conn.close()


def test_cache_has_no_api_keys_and_no_restored_marks():
    files = cache_files()
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not SECRET_LIKE.search(text), f"похоже на ключ API: {path.name}"
        assert "restored_from" not in text, f"восстановленная запись: {path.name}"
        assert not [t for t in LONG_TOKEN.findall(text) if not SHA256.fullmatch(t)], f"длинная строка, похожая на секрет: {path.name}"
    usage = REAL_CACHE / "_usage.json"
    if usage.exists():
        assert not SECRET_LIKE.search(usage.read_text(encoding="utf-8"))
