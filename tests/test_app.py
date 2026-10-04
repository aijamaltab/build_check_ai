"""app.py целиком через streamlit.testing (без браузера): демо в режиме llm из реального кэша, без ключа и API."""
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.cache_guard import REAL_CACHE

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def llm_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))        # реальный кэш, только чтение
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))     # база приложения во временной папке теста


def test_app_shows_demo_in_llm_mode_with_13_issues(llm_env):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    assert not at.exception
    assert [i.value for i in at.info] == ["Демо, синтетические данные"]
    assert len(at.warning) == 0                                              # баннера и предупреждения про светофор нет
    assert any("Режим: С ИИ" in c.value for c in at.caption)
    assert any("окончательное решение за специалистом" in c.value for c in at.caption)
    assert any(s.value.startswith("Проверено 180 позиций, не распознано 0, не сопоставлено 3, из них требует проверки 0, "
                                  "не сопоставимо 0; расхождений 13") for s in at.subheader)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Красные позиции"] == "11" and metrics["Жёлтые позиции"] == "7" and metrics["Зелёные позиции"] == "30"
    assert metrics["Возможное влияние на бюджет"] == "1 378 030 сом"
    table = at.dataframe[0].value
    assert len(table) == 13 and table["Источник"].str.contains(" · лист «").all()
