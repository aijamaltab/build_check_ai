"""Кэш ответов LLM: один JSON-файл на запрос в data/cache/llm/ (лежит в репозитории, демо идёт без ключа).

Ключ = sha256 от (функция, модель, версия промта, schema_version, нормализованный вход). Хранится ответ модели,
имя модели, версия промта, время и нормализованный вход (для отладки). Секретов в записи нет: ключ API сюда не попадает.
Один файл на запрос: два человека пишут в кэш параллельно без конфликтов слияния.
"""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path


def normalize_text(text) -> str:
    """Вход для ключа кэша: регистр и пробелы не меняют ключ."""
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def cache_key(function: str, model: str, prompt_version: str, schema_version, payload: dict) -> str:
    body = json.dumps({"function": function, "model": model, "prompt_version": prompt_version,
                       "schema_version": schema_version, "payload": payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class LlmCache:
    def __init__(self, directory, write: bool = True):
        self.dir = Path(directory)
        self.write = write

    def is_empty(self) -> bool:
        return not self.dir.is_dir() or not any(self.dir.glob("*.json"))

    def get(self, key: str):
        """-> запись кэша или None (нет файла или файл повреждён)."""
        path = self.dir / f"{key}.json"
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return record if isinstance(record, dict) and "answer" in record else None

    def put(self, key: str, answer, *, function: str, model: str, prompt_version: str, payload: dict) -> None:
        if not self.write:
            return
        record = {"function": function, "model": model, "prompt_version": prompt_version,
                  "created_at": dt.datetime.now().isoformat(timespec="seconds"), "payload": payload, "answer": answer}
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f"{key}.json.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.dir / f"{key}.json")
