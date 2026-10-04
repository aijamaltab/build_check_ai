"""Тесты не ходят в сеть и не зависят от ключа и от кэша в репозитории."""
import pytest


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch, tmp_path_factory):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_CACHE_ONLY", raising=False)
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path_factory.mktemp("llm_cache")))
