"""Сборка результатов демо один раз на режим (st.cache_resource): отдельный файл базы на режим, дальше только чтение."""
import logging
import tempfile
from pathlib import Path

import streamlit as st

from src.pipeline import run_pipeline
from ui.data import load_results

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "data" / "synthetic"
log = logging.getLogger("app")


@st.cache_resource(show_spinner="Строим результат из демо-проекта…")
def build_demo(mode: str) -> dict:
    db_dir = Path(tempfile.gettempdir()) / "hackathon_ai_demo"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = db_dir / f"demo_{mode}.db"
    summary = run_pipeline(DEMO_DIR, db, mode)
    results = load_results(db)
    results["files"] = summary["files"]
    log.warning("demo built: requested=%s mode=%s files=%s issues=%s", mode, summary["mode"], summary["files"], summary["z"])
    return results
