"""Тесты не ходят в сеть, не зависят от ключа и не трогают реальный кэш data/cache/llm/."""
import pytest

from tests.cache_guard import REAL_CACHE, changes, snapshot


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch, tmp_path_factory):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_CACHE_ONLY", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path_factory.mktemp("llm_cache")))
    before = snapshot()
    yield
    modified = changes(before, snapshot())
    assert not modified, f"тест изменил реальный кэш {REAL_CACHE}: {', '.join(modified)}"
