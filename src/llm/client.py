"""Клиент Gemini: кэш, режим «только кэш», повтор, счётчики. Общий каркас для всех ИИ-функций (судья пар, RowMatcher, объяснения).

Правила (CLAUDE.md §3): температура 0, ответ только JSON, ключ только из переменной окружения (llm.api_key_env) и нигде не
печатается, не пишется в кэш и не попадает в тексты ошибок. Любой сбой (сеть, 429, пустой ответ, невалидный JSON) это один
повтор с паузой, затем «нет ответа» (None), а не исключение: прогон продолжается без ИИ для этой строки.
Сам вызов API спрятан в transport (callable), в тестах это фейк без сети.
"""
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .cache import LlmCache, cache_key

ROOT = Path(__file__).resolve().parents[2]
TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class LlmStats:
    calls: int = 0               # обращений к API (включая повторы)
    errors: int = 0              # неудачные обращения: сеть, 429, пустой или невалидный ответ
    cache_hits: int = 0
    no_answer: int = 0           # запросов, закончившихся «нет ответа»
    low_confidence: int = 0      # ответ есть, но уверенность ниже llm.min_confidence: решения нет
    rejected_by_check: int = 0   # ответ модели противоречит жёсткому правилу кода

    def as_dict(self) -> dict:
        return asdict(self)


class GenaiTransport:
    """Настоящий вызов через официальный SDK google-genai (тот же способ, что в проверочном скрипте)."""

    def __init__(self, api_key: str, model: str, temperature: float, timeout: float):
        from google import genai
        from google.genai import types
        self._types = types
        self.model, self.temperature = model, temperature
        self.client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))

    def __call__(self, prompt: str, schema: dict) -> str:
        t = self._types
        response = self.client.models.generate_content(
            model=self.model, contents=prompt,
            config=t.GenerateContentConfig(temperature=self.temperature, response_mime_type="application/json",
                                           response_schema=schema))
        return response.text


class LlmClient:
    def __init__(self, llm_cfg: dict, *, transport=None, cache: LlmCache | None = None, sleep=time.sleep,
                 clock=time.monotonic, env=None, root: Path = ROOT):
        env = os.environ if env is None else env
        self.cfg = llm_cfg
        self.model = llm_cfg["model"]
        self.stats = LlmStats()
        self.last_error = None
        self._key = env.get(llm_cfg["api_key_env"]) or None
        self.cache_only = bool(llm_cfg.get("cache_only")) or env.get(llm_cfg.get("cache_only_env", ""), "").lower() in TRUTHY
        cache_dir = env.get(llm_cfg.get("cache_dir_env", "")) or llm_cfg["cache_dir"]
        self.cache = cache or LlmCache(Path(cache_dir) if Path(cache_dir).is_absolute() else root / cache_dir,
                                       write=llm_cfg.get("cache_write", True))
        self._transport = transport
        self._sleep, self._clock = sleep, clock
        self._last_call = None

    @property
    def has_key(self) -> bool:
        return self._key is not None

    @property
    def can_call_api(self) -> bool:
        """Режим «только кэш» запрещает вызовы API, даже если есть ключ."""
        return not self.cache_only and (self._transport is not None or self.has_key)

    @property
    def available(self) -> bool:
        """ИИ можно использовать: можно вызывать API или в кэше есть ответы."""
        return self.can_call_api or not self.cache.is_empty()

    def _scrub(self, text) -> str:
        text = str(text)
        return text.replace(self._key, "***") if self._key else text

    def _call_transport(self, prompt: str, schema: dict) -> str:
        if self._transport is None:
            self._transport = GenaiTransport(self._key, self.model, self.cfg["temperature"], self.cfg["timeout"])
        return self._transport(prompt, schema)

    def _pause_between_calls(self) -> None:
        gap = self.cfg.get("call_pause_seconds", 0)
        if self._last_call is not None and gap:
            wait = gap - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)

    def ask(self, function: str, prompt_version: str, payload: dict, prompt: str, schema: dict, validate):
        """-> ответ модели (словарь, прошедший validate) или None. payload: нормализованный вход, он идёт в ключ кэша."""
        key = cache_key(function, self.model, prompt_version, self.cfg["schema_version"], payload)
        record = self.cache.get(key)
        if record is not None and validate(record["answer"]):
            self.stats.cache_hits += 1
            return record["answer"]
        if not self.can_call_api:                                  # режим «только кэш» или нет ключа: API не вызываем
            self.stats.no_answer += 1
            return None
        retries = int(self.cfg["max_retries"])
        for attempt in range(retries + 1):
            self._pause_between_calls()
            self.stats.calls += 1
            rate_limited = False
            try:
                text = self._call_transport(prompt, schema)
                self._last_call = self._clock()
                answer = json.loads(text) if text and text.strip() else None
                if answer is None:
                    raise ValueError("пустой ответ")
                if not validate(answer):
                    raise ValueError("ответ не по схеме")
            except Exception as e:  # noqa: BLE001: любой сбой это «нет ответа» после повтора
                self._last_call = self._clock()
                code = getattr(e, "code", None)
                rate_limited = code == 429 or "429" in str(e)[:200] or "RESOURCE_EXHAUSTED" in str(e)[:200]
                self.stats.errors += 1
                self.last_error = f"{type(e).__name__}" + (f" {code}" if code else "") + f": {self._scrub(e)[:300]}"
                if attempt < retries:
                    pause = self.cfg["retry_pause_seconds"] * (2 ** attempt if rate_limited else 1)
                    self._sleep(min(pause, self.cfg["retry_max_pause_seconds"]))
                continue
            self.cache.put(key, answer, function=function, model=self.model, prompt_version=prompt_version,
                           payload=payload)
            return answer
        self.stats.no_answer += 1
        return None
