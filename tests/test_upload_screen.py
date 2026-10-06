"""Тесты страницы «Проверить свои файлы» (ui/screens/upload.py) через AppTest."""
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.pipeline import run_pipeline
from tests.cache_guard import REAL_CACHE
from ui.data import load_results

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "data" / "synthetic"


@pytest.fixture()
def llm_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(REAL_CACHE))
    monkeypatch.setenv("LLM_CACHE_ONLY", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))


def upload_app():
    import os
    os.environ.setdefault("LLM_CACHE_ONLY", "1")
    from ui.screens import upload
    upload.render()


def test_upload_page_initial_render(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    assert not at.exception
    html = "\n".join(m.value for m in at.markdown)
    assert "Загрузите свои файлы для сверки" in html
    assert "Ваши данные" in html
    assert "Для новых названий ИИ-ответов в демо-кэше нет" not in html      # цитата убрана, остался один синий блок
    assert sum("Для новых названий ИИ-ответов в демо-кэше нет" in i.value for i in at.info) == 1
    assert len(at.file_uploader) == 4    # vor, estimate, contract, acts
    assert len(at.button) >= 1
    assert at.button[0].label == "Сверить"


def test_upload_page_validation_empty(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    at.button[0].click().run()
    assert not at.exception
    assert len(at.error) >= 1
    assert "Пожалуйста, загрузите" in at.error[0].value


def test_upload_page_with_synthetic_results(llm_env, tmp_path):
    # Запускаем pipeline на синтетических данных во временную БД
    db_path = tmp_path / "upload_test.db"
    summary = run_pipeline(DEMO_DIR, db_path, mode="llm", project_id="upload")
    results = load_results(db_path, project_id="upload")
    results["n_files"] = summary["files"]

    at = AppTest.from_function(upload_app, default_timeout=60)
    at.session_state["upload_results"] = results
    at.session_state["upload_summary"] = summary
    at.run()

    assert not at.exception
    html = "\n".join(m.value for m in at.markdown)

    # результат на этой же странице: метрики, кнопка отчёта и та же сверочная ведомость (компонент)
    assert "Результат сверки" in html
    assert "Строк в документах" in html and "1 378 030" in html
    assert len(at.get("iframe")) == 1 and len(at.download_button) == 1
    assert 'class="issue-card"' not in html


def test_upload_page_broken_files_message(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60)
    at.session_state["upload_summary"] = {"files": 0, "documents_with_errors": ["corrupt.xlsx"]}
    at.session_state["upload_results"] = {"files": None, "issues": None, "positions": None}
    at.run()

    assert not at.exception
    assert len(at.error) >= 1
    assert "не были распознаны" in at.error[0].value
    assert any("corrupt.xlsx" in w.value for w in at.warning)


def test_upload_real_files_end_to_end(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    assert not at.exception

    # Загружаем файлы демо-проекта
    for f in ("vor_1.xlsx", "vor_2.xlsx"):
        at.file_uploader[0].upload(f, (DEMO_DIR / f).read_bytes())
    at.file_uploader[1].upload("estimate.xlsx", (DEMO_DIR / "estimate.xlsx").read_bytes())
    at.file_uploader[2].upload("contract.xlsx", (DEMO_DIR / "contract.xlsx").read_bytes())
    for f in ("act_1.xlsx", "act_2.xlsx", "act_3.xlsx", "act_4.xlsx", "act_5.xlsx"):
        at.file_uploader[3].upload(f, (DEMO_DIR / f).read_bytes())

    at.button[0].click().run()
    assert not at.exception

    html = "\n".join(m.value for m in at.markdown)
    assert "Результат сверки" in html and "1 378 030" in html and len(at.get("iframe")) == 1


def test_upload_broken_file_end_to_end(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    assert not at.exception

    # Загружаем поврежденный файл вместо ВОР
    at.file_uploader[0].upload("broken_vor.xlsx", b"invalid excel content not a zip")
    at.file_uploader[3].upload("act_1.xlsx", (DEMO_DIR / "act_1.xlsx").read_bytes())

    at.button[0].click().run()
    assert not at.exception

    # Никакого traceback, понятное сообщение
    html = "\n".join(m.value for m in at.markdown)
    assert len(at.warning) >= 1
    assert any("broken_vor.xlsx" in w.value for w in at.warning)


def test_upload_rejects_big_files(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    at.file_uploader[0].upload("vor.xlsx", b"x" * (5 * 1024 * 1024 + 1))
    at.file_uploader[3].upload("act_1.xlsx", (DEMO_DIR / "act_1.xlsx").read_bytes())
    at.button[0].click().run()
    assert not at.exception
    assert any("vor.xlsx" in e.value and "больше 5 МБ" in e.value for e in at.error)
    assert "upload_results" not in at.session_state


def test_upload_removes_temp_files(llm_env, tmp_path):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    at.file_uploader[0].upload("vor_1.xlsx", (DEMO_DIR / "vor_1.xlsx").read_bytes())
    at.file_uploader[3].upload("act_1.xlsx", (DEMO_DIR / "act_1.xlsx").read_bytes())
    at.button[0].click().run()
    assert not at.exception
    assert list(tmp_path.glob("buildcheck_upload_*")) == []
