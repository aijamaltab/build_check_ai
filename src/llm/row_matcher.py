"""GeminiRowMatcher: RowMatcher на Gemini (docs/synthetic_spec.md §10, функция «а2»).

Модель видит список всех позиций ВОР (номера K1, K2, ... по порядку ключей) и пачку нерешённых строк документов (до
llm.row_batch_size за вызов), выбирает позицию из списка или отвечает key = null («в ВОР нет»). Решает код: ключ должен быть из
списка, единица совпадает, вид (если известен у обеих сторон), числовые токены и слова взаимоисключающих групп не обходятся
ответом (как у GeminiPairJudge); уверенность ниже llm.min_confidence это «нет решения». «Один ключ на группу в документе»
и применение ответов по убыванию уверенности делает resolve_rows. Цена и количество в промт не передаются.

Кэш по строке (а не по пачке): ключ = модель, версия промта, нормализованные название, единица и вид строки, хеш списка ВОР.
Правка одной строки не обнуляет кэш остальных; в пачку идут только строки без записи. Правка списка ВОР меняет хеш и обнуляет
кэш всех строк (ответы зависят от списка).
Нет ответа возвращается как None (строка остаётся ambiguous или absent без подтверждения), подтверждённое «нет» как key = None
с достаточной уверенностью: именно оно даёт missing_in_vor высокой уверенности.
"""
import hashlib
import json

from src.matching.names import NameNormalizer

from .cache import normalize_text
from .client import LlmClient
from .pair_judge import KNOWN_KINDS
from .prompts import ROW_PROMPT_VERSION, ROW_SCHEMA, build_row_prompt

CHECK_PREFIX = "отклонено проверкой"


def key_ids(vor_keys: list) -> dict:
    """Ключ ВОР -> короткий номер в промте (K1, K2, ...) в порядке сортировки ключей: порядок не зависит от порядка строк в файле."""
    return {k: f"K{i}" for i, k in enumerate(sorted(v["key"] for v in vor_keys), 1)}


def vor_hash(vor_keys: list) -> str:
    """Хеш списка ВОР (ключ, название, единица, вид): входит в ключ кэша каждой строки."""
    items = sorted([v["key"], normalize_text(v["name_raw"]), v["unit"] or "-", v["kind"] or "-"] for v in vor_keys)
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()


def _item_ok(item) -> bool:
    return (isinstance(item, dict) and isinstance(item.get("row_id"), int) and not isinstance(item.get("row_id"), bool)
            and (item.get("key") is None or isinstance(item.get("key"), str))
            and isinstance(item.get("confidence"), (int, float)) and not isinstance(item.get("confidence"), bool)
            and 0 <= item["confidence"] <= 1 and isinstance(item.get("reason"), str))


def valid_batch_response(response) -> bool:
    """Ответ пачки по схеме: список answers, хотя бы один элемент целиком валиден (остальные просто отбрасываются)."""
    return (isinstance(response, dict) and isinstance(response.get("answers"), list)
            and any(_item_ok(i) for i in response["answers"]))


def _cached_ok(answer) -> bool:
    return (isinstance(answer, dict) and (answer.get("key") is None or isinstance(answer.get("key"), str))
            and isinstance(answer.get("confidence"), (int, float)) and not isinstance(answer.get("confidence"), bool)
            and 0 <= answer["confidence"] <= 1 and isinstance(answer.get("reason"), str))


class GeminiRowMatcher:
    def __init__(self, client: LlmClient, cfg: dict):
        self.client = client
        llm = cfg["rules"]["llm"]
        self.min_confidence = llm["min_confidence"]
        self.batch_size = max(1, int(llm.get("row_batch_size", 10)))
        self.hard = set(llm.get("judge_hard_conflicts", ["patterns"]))
        self.norm = NameNormalizer(cfg["synonyms"], cfg["rules"], True)

    available = property(lambda self: self.client.available)
    stats = property(lambda self: self.client.stats)
    stop_reason = property(lambda self: self.client.stop_reason)
    warnings = property(lambda self: self.client.warnings)

    def match_row(self, row: dict, vor_keys: list):
        return self.match_rows([row], vor_keys)[0]

    def _check(self, row: dict, vor: dict) -> str | None:
        """Причина, по которой выбор модели недопустим (проверка кодом), или None."""
        if row.get("unit") is None or row.get("unit") != vor.get("unit"):
            return f"единицы различаются: {row.get('unit')} и {vor.get('unit')}"
        if row.get("kind") in KNOWN_KINDS and vor.get("kind") in KNOWN_KINDS and row["kind"] != vor["kind"]:
            return f"вид различается: {row['kind']} и {vor['kind']}"
        conflicts = self.norm.conflicts(self.norm.prepare(row["name"]), self.norm.prepare(vor["name"]))
        hard = [text for kind, text in conflicts if kind in self.hard]
        return "; ".join(hard) if hard else None

    def match_rows(self, rows: list, vor_keys: list) -> list:
        """-> список ответов по порядку rows: {key, confidence, reason} или None (нет решения)."""
        ids = key_ids(vor_keys)
        by_id = {i: k for k, i in ids.items()}
        vor_by_key = {v["key"]: v for v in vor_keys}
        vor_items = [(ids[v["key"]], v) for v in sorted(vor_keys, key=lambda v: v["key"])]
        listing_hash = vor_hash(vor_keys)

        units = {}                                    # ключ кэша -> строка (одинаковые строки спрашиваем один раз)
        row_cache_key = []
        for row in rows:
            payload = {"row": [normalize_text(row["name_raw"]), row.get("unit") or "-", row.get("kind") or "-"],
                       "vor": listing_hash}
            ck = self.client.key_for("row", ROW_PROMPT_VERSION, payload)
            row_cache_key.append(ck)
            units.setdefault(ck, {"row": row, "payload": payload})

        def valid_cached(answer):
            return _cached_ok(answer) and (answer["key"] is None or answer["key"] in vor_by_key)

        answers, pending = {}, []
        for ck in units:
            hit = self.client.cached(ck, valid_cached)
            if hit is not None:
                answers[ck] = hit
            else:
                pending.append(ck)

        notify = getattr(self, "progress", None)
        if notify:
            notify("rows", len(units) - len(pending), len(units))
        for start in range(0, len(pending), self.batch_size):
            chunk = pending[start:start + self.batch_size]
            prompt = build_row_prompt([units[ck]["row"] for ck in chunk], vor_items)
            response = self.client.generate(prompt, ROW_SCHEMA, valid_batch_response)
            by_row = {i["row_id"]: i for i in (response or {}).get("answers", []) if _item_ok(i)}
            for position, ck in enumerate(chunk, 1):
                item = by_row.get(position)
                if item is None:                      # нет ответа API или модель пропустила строку
                    self.client.stats.no_answer += 1
                    continue
                if item["key"] is not None and item["key"] not in by_id:   # ключ вне списка: не принимаем и не кэшируем
                    self.client.stats.rejected_by_check += 1
                    continue
                answer = {"key": by_id[item["key"]] if item["key"] is not None else None,
                          "confidence": float(item["confidence"]), "reason": item["reason"]}
                self.client.store(ck, answer, "row", ROW_PROMPT_VERSION, units[ck]["payload"])
                answers[ck] = answer
            if notify:
                notify("rows", len(units) - len(pending) + min(start + self.batch_size, len(pending)), len(units))

        results = []
        for row, ck in zip(rows, row_cache_key):
            answer = answers.get(ck)
            if answer is None:
                results.append(None)
            elif answer["confidence"] < self.min_confidence:
                self.client.stats.low_confidence += 1
                results.append(None)                  # низкая уверенность (и «нет», и ключа) это нет решения
            elif answer["key"] is None:
                results.append(dict(answer))          # подтверждённое «в ВОР нет»
            else:
                reason = self._check(row, vor_by_key[answer["key"]])
                if reason:
                    self.client.stats.rejected_by_check += 1
                    results.append({"key": None, "confidence": 0.0,
                                    "reason": f"{CHECK_PREFIX}: {reason} (ответ модели: {answer['reason']})"})
                else:
                    results.append(dict(answer))
        return results
