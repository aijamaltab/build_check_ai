"""Прогон сверки для интерфейса. Одна сессия посетителя = одна временная папка с базой и копией файлов.

Результат лежит в st.session_state["run_result"], его читают страницы «Результаты» и «Исходные таблицы». Базы разных сессий
не пересекаются, общую демо-базу (ui.loader.build_demo, нужна странице «Как работает ИИ») прогон не трогает.
Демо-наборы берут ответы ИИ только из кэша (ключ не используется); живой ИИ включается лишь при загрузке своих файлов."""
import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st

from src.config import load_config
from src.llm.budget import CallBudget
from src.pipeline import run_pipeline
from ui.data import load_results
from ui.live_ai import build_live_ai
from ui.sets import set_dir

RUN_KEY = "run_result"
WORK_PREFIX = "buildcheck_run_"
STALE_SECONDS = 6 * 3600       # папки старше шести часов считаются брошенными (сессия закрыта) и удаляются при следующем прогоне
PROJECT_ID = "run"


def purge_stale(max_age: float = STALE_SECONDS) -> None:
    """Удаляет брошенные рабочие папки прогонов (их не удалила закрытая сессия)."""
    now = time.time()
    for path in Path(tempfile.gettempdir()).glob(f"{WORK_PREFIX}*"):
        try:
            if path.is_dir() and now - path.stat().st_mtime > max_age:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def drop_run(run: dict | None) -> None:
    if run and run.get("workdir"):
        shutil.rmtree(run["workdir"], ignore_errors=True)


def current_run() -> dict | None:
    """Результат последнего прогона этой сессии; None, если прогона нет или его папка уже удалена."""
    run = st.session_state.get(RUN_KEY)
    if run and Path(run["db_path"]).exists():
        return run
    return None


def reset_run() -> None:
    drop_run(st.session_state.pop(RUN_KEY, None))


def _compare_without_ai(set_name: str | None):
    """Режим без ИИ для сравнения «было / стало»: эталон заложенных расхождений есть только у базового демо-набора."""
    if set_name != "base":
        return None
    from ui.loader import build_demo
    return build_demo("rules_only")


def recognised(run: dict) -> bool:
    """Хотя бы один файл прочитан и есть таблица файлов."""
    files = run["results"].get("files")
    return bool(run["summary"].get("files")) and files is not None and not files.empty


def execute(source: Path, label: str, *, set_name: str | None = None, files: list | None = None, key: str | None = None,
            session: CallBudget | None = None, site: CallBudget | None = None, progress=None) -> dict:
    """Сверка папки source (или загруженных files = [(имя, байты)]) в новой рабочей папке; результат кладёт в session_state.

    Ошибки не гасит: страница показывает их пользователю. При ошибке или если ни один файл не распознан, рабочая папка удаляется
    (в session_state не попадает), прошлый результат остаётся."""
    purge_stale()
    cfg = load_config()
    workdir = Path(tempfile.mkdtemp(prefix=WORK_PREFIX))
    try:
        if files is not None:
            source = workdir / "files"
            source.mkdir()
            for name, data in files:
                (source / Path(name).name).write_bytes(data)
        judge, row_matcher, live = build_live_ai(cfg, key, session or CallBudget(0), site or CallBudget(0, daily=True), progress)
        db_path = workdir / "run.db"
        summary = run_pipeline(str(source), db_path, mode="llm", judge=judge, row_matcher=row_matcher, project_id=PROJECT_ID, cfg=cfg)
        results = load_results(db_path, project_id=PROJECT_ID)
        results["n_files"] = summary["files"]
        run = {"results": results, "summary": summary, "label": label, "live": live, "set_name": set_name, "project_id": PROJECT_ID,
               "db_path": str(db_path), "files_dir": str(source), "workdir": str(workdir), "run_at": results.get("run_at"),
               "compare": _compare_without_ai(set_name) if summary.get("files") else None}
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    if not recognised(run):                       # ничего не прочитано: прошлый результат сессии остаётся, эта папка не нужна
        shutil.rmtree(workdir, ignore_errors=True)
        return run
    drop_run(st.session_state.get(RUN_KEY))
    st.session_state[RUN_KEY] = run
    return run


def execute_set(set_name: str, label: str, progress=None) -> dict:
    """Готовый демо-набор: ответы ИИ только из кэша."""
    return execute(set_dir(set_name), label, set_name=set_name, key=None, progress=progress)


def mode_label(run: dict) -> str:
    """Режим прогона одной строкой для шапки: с ИИ (из кэша или живые запросы) или без ИИ."""
    if run["summary"].get("mode") != "llm":
        return "Без ИИ (базовый режим)"
    return "С ИИ (живые запросы и кэш)" if run.get("live") else "С ИИ (из кэша)"
