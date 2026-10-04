"""Защита реального кэша: снимок замечает добавление, удаление и изменение файла."""
import os

from tests.cache_guard import REAL_CACHE, changes, snapshot


def test_snapshot_detects_added_removed_and_modified_files(tmp_path):
    (tmp_path / "a.json").write_text("1")
    (tmp_path / "b.json").write_text("2")
    before = snapshot(tmp_path)
    (tmp_path / "c.json").write_text("3")
    (tmp_path / "a.json").write_text("1111")
    os.utime(tmp_path / "b.json", ns=(1, 1))
    after = snapshot(tmp_path)
    assert changes(before, after) == ["добавлен c.json", "изменён a.json", "изменён b.json"]
    (tmp_path / "c.json").unlink()
    assert "удалён c.json" in changes(after, snapshot(tmp_path))
    assert changes(before, before) == []


def test_missing_directory_gives_empty_snapshot(tmp_path):
    assert snapshot(tmp_path / "нет") == {}


def test_llm_cache_dir_is_redirected_away_from_repo_cache():
    cache_dir = os.environ["LLM_CACHE_DIR"]
    assert os.path.realpath(cache_dir) != os.path.realpath(REAL_CACHE)
    assert not os.path.realpath(cache_dir).startswith(os.path.realpath(REAL_CACHE))
