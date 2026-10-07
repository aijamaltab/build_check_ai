"""Готовые синтетические наборы для проверки: список, файлы и zip для скачивания. Без Streamlit.
base это демо-проект data/synthetic, остальные лежат в data/synthetic_sets."""
import io
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETS_DIR = ROOT / "data" / "synthetic_sets"
BASE_DIR = ROOT / "data" / "synthetic"
SETS = {"base": "Базовый набор: капремонт школы", "set_3": "Набор 3: капремонт амбулатории", "set_4": "Набор 4: капремонт дома культуры"}
FIXED_TIME = (2025, 1, 1, 0, 0, 0)


def set_dir(name: str) -> Path:
    return BASE_DIR if name == "base" else SETS_DIR / name


def set_files(name: str) -> list:
    """Файлы набора (только xlsx; эталон ground_truth.csv в zip не кладём), по алфавиту."""
    return sorted(set_dir(name).glob("*.xlsx"))


def zip_bytes(name: str) -> bytes:
    """zip с девятью xlsx набора (одинаковые байты при каждом вызове)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path in set_files(name):
            info = zipfile.ZipInfo(path.name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    return buf.getvalue()
