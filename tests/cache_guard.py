"""Защита реального кэша data/cache/llm/: снимок (файл, размер, mtime) до и после теста."""
from pathlib import Path

REAL_CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "llm"


def snapshot(directory: Path = REAL_CACHE) -> dict:
    if not directory.is_dir():
        return {}
    return {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in directory.iterdir() if p.is_file()}


def changes(before: dict, after: dict) -> list:
    out = [f"добавлен {n}" for n in after.keys() - before.keys()]
    out += [f"удалён {n}" for n in before.keys() - after.keys()]
    out += [f"изменён {n}" for n in before.keys() & after.keys() if before[n] != after[n]]
    return sorted(out)
