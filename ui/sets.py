"""Готовые синтетические наборы для проверки (data/synthetic_sets): список, файлы и zip для скачивания. Без Streamlit."""
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETS_DIR = ROOT / "data" / "synthetic_sets"
SETS = {"set_2": "Набор 2: капремонт детского сада", "set_3": "Набор 3: капремонт амбулатории"}
FIXED_TIME = (2025, 1, 1, 0, 0, 0)


def set_files(name: str) -> list:
    """Файлы набора (только xlsx; эталон ground_truth.csv в zip не кладём), по алфавиту."""
    return sorted((SETS_DIR / name).glob("*.xlsx"))


def zip_bytes(name: str) -> bytes:
    """zip с девятью xlsx набора (одинаковые байты при каждом вызове)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in set_files(name):
            info = zipfile.ZipInfo(path.name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    return buf.getvalue()
