"""Тесты страницы «Загрузка данных» (ui/screens/upload.py) через AppTest."""
import tempfile
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from tests.cache_guard import REAL_CACHE

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


def add(at, key, name):
    at.file_uploader(key=key).upload(name, (DEMO_DIR / name).read_bytes())


def test_upload_page_initial_render(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    assert not at.exception
    html = "\n".join(m.value for m in at.markdown)
    assert "Сверка строительных документов" in html
    assert sum("Живой ИИ на этом сайте сейчас выключен" in i.value for i in at.info) == 1       # без ключа: честное сообщение, один блок
    assert not at.warning                                                                  # предупреждение о внешнем сервисе только при живом ИИ
    assert "Попробуйте на демо-наборе" in html and "Синтетические данные" in html
    assert [d.label for d in at.download_button] == ["Скачать набор (zip)"] * 3
    assert [b.label for b in at.button] == ["Посмотреть результат"] * 3 + ["Сверить"]
    assert len(at.file_uploader) == 4    # vor, акты, смета, договор


def test_upload_page_validation_empty(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    at.button(key="upload_run").click().run()
    assert not at.exception
    assert len(at.error) >= 1
    assert "Пожалуйста, загрузите" in at.error[0].value
    assert "run_result" not in at.session_state


def test_upload_real_files_end_to_end(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    assert not at.exception
    add(at, "upload_vor", "vor_1.xlsx")
    add(at, "upload_estimate", "estimate.xlsx")
    for f in ("act_1.xlsx", "act_2.xlsx"):
        add(at, "upload_acts", f)
    at.button(key="upload_run").click().run()
    assert not at.exception and not at.error
    run = at.session_state["run_result"]
    assert run["label"] == "загруженные файлы" and run["set_name"] is None and run["live"] is False
    assert run["summary"]["files"] == 4 and run["summary"]["ai"]["calls"] == 0
    assert Path(run["files_dir"]).is_dir() and sorted(p.name for p in Path(run["files_dir"]).iterdir()) == ["act_1.xlsx", "act_2.xlsx", "estimate.xlsx", "vor_1.xlsx"]


def test_same_files_as_the_demo_give_the_same_result(llm_env):
    """DoD п. 3: девять файлов демо, загруженные вручную, дают тот же результат, что кнопка демо."""
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    for name in ("vor_1.xlsx", "vor_2.xlsx"):
        add(at, "upload_vor", name)
    add(at, "upload_estimate", "estimate.xlsx")
    add(at, "upload_contract", "contract.xlsx")
    for n in range(1, 6):
        add(at, "upload_acts", f"act_{n}.xlsx")
    at.button(key="upload_run").click().run()
    assert not at.exception and not at.error
    uploaded = at.session_state["run_result"]["summary"]
    at.button(key="run_base").click().run()
    demo = at.session_state["run_result"]["summary"]
    assert uploaded["files"] == demo["files"] == 9
    assert (uploaded["z"], uploaded["impact_som"], uploaded["statuses"]) == (demo["z"], demo["impact_som"], demo["statuses"]) == (13, 1378030.0, demo["statuses"])


def test_upload_rejects_more_than_nine_files(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    add(at, "upload_vor", "vor_1.xlsx")
    for n in range(1, 6):
        add(at, "upload_acts", f"act_{n}.xlsx")
    for n in range(1, 5):
        at.file_uploader(key="upload_estimate").upload(f"estimate_{n}.xlsx", (DEMO_DIR / "estimate.xlsx").read_bytes())
    at.button(key="upload_run").click().run()
    assert not at.exception and any("максимум 9" in e.value for e in at.error)
    assert "run_result" not in at.session_state


def test_upload_broken_file_with_one_good_act_keeps_result_and_reports_error(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    at.file_uploader(key="upload_vor").upload("broken_vor.xlsx", b"invalid excel content not a zip")
    add(at, "upload_acts", "act_1.xlsx")
    at.button(key="upload_run").click().run()
    assert not at.exception
    run = at.session_state.get("run_result")
    assert run is not None and "broken_vor.xlsx" in run["summary"]["documents_with_errors"]       # на «Результатах» будет предупреждение


def test_upload_only_broken_files_shows_message_and_no_result(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    at.file_uploader(key="upload_vor").upload("broken_vor.xlsx", b"invalid excel content not a zip")
    at.file_uploader(key="upload_acts").upload("broken_act.xlsx", b"also not a zip")
    at.button(key="upload_run").click().run()
    assert not at.exception
    assert any("не были распознаны" in e.value for e in at.error) and "run_result" not in at.session_state


def test_upload_rejects_big_files(llm_env):
    at = AppTest.from_function(upload_app, default_timeout=60).run()
    at.file_uploader(key="upload_vor").upload("vor.xlsx", b"x" * (5 * 1024 * 1024 + 1))
    add(at, "upload_acts", "act_1.xlsx")
    at.button(key="upload_run").click().run()
    assert not at.exception
    assert any("vor.xlsx" in e.value and "больше 5 МБ" in e.value for e in at.error)
    assert "run_result" not in at.session_state


def test_failed_run_leaves_no_temp_folders_and_keeps_previous_result(llm_env, tmp_path):
    at = AppTest.from_function(upload_app, default_timeout=180).run()
    at.button(key="run_base").click().run()
    kept = at.session_state["run_result"]["db_path"]
    at.file_uploader(key="upload_vor").upload("broken_vor.xlsx", b"invalid excel content not a zip")
    at.file_uploader(key="upload_acts").upload("broken_act.xlsx", b"also not a zip")
    at.button(key="upload_run").click().run()
    assert any("не были распознаны" in e.value for e in at.error)
    assert at.session_state["run_result"]["db_path"] == kept and Path(kept).exists()                # прошлый результат не повреждён
    assert len(list(tmp_path.glob("buildcheck_run_*"))) == 1                                        # папка неудачного прогона удалена
