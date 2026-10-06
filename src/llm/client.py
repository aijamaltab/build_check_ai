"""Клиент Gemini: кэш, режим «только кэш», повтор, счётчики. Общий каркас для всех ИИ-функций (судья пар, RowMatcher, объяснения).

Правила (CLAUDE.md §3): температура 0, ответ только JSON, ключ только из переменной окружения (llm.api_key_env) и нигде не
печатается, не пишется в кэш и не попадает в тексты ошибок. Любой сбой (сеть, 429, пустой ответ, невалидный JSON) это один
повтор с паузой, затем «нет ответа» (None), а не исключение: прогон продолжается без ИИ для этой строки.
Сам вызов API спрятан в transport (callable), в тестах это фейк без сети.
"""
import json
import datetime as dt
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .cache import LlmCache, UsageCounter, cache_key

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
    quota_errors: int = 0        # из errors: ответы 429 (квота)

    def as_dict(self) -> dict:
        return asdict(self)


RETRY_DELAY_PATTERNS = [
    re.compile(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)\s*s", re.I),     # RetryInfo в JSON: "retryDelay": "37s"
    re.compile(r"retry[_ ]delay\s*\{\s*seconds:\s*(\d+)", re.I),               # то же в текстовом виде protobuf
    re.compile(r"retry in (\d+(?:\.\d+)?)\s*s", re.I),                          # «Please retry in 37.5s»
]


def parse_quota_error(exc) -> tuple[float | None, bool]:
    """-> (рекомендованная пауза в секундах или None, суточный ли лимит) по тексту и деталям ошибки 429.
    Формат ответа Google (RetryInfo, QuotaFailure) взят из документации, на живом API не проверялся: если полей нет,
    возвращается (None, False) и клиент ждёт по запасной схеме."""
    parts = [str(exc)]
    details = getattr(exc, "details", None)
    if details:
        parts.append(json.dumps(details, ensure_ascii=False, default=str))
    blob = " ".join(parts)
    delay = None
    for pattern in RETRY_DELAY_PATTERNS:
        m = pattern.search(blob)
        if m:
            delay = float(m.group(1))
            break
    daily = bool(re.search(r"PerDay|per day|daily|в сутки", blob, re.I))
    return delay, daily


def is_rate_limited(exc) -> bool:
    return getattr(exc, "code", None) == 429 or "429" in str(exc)[:200] or "RESOURCE_EXHAUSTED" in str(exc)[:200]


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
                 clock=time.monotonic, env=None, root: Path = ROOT, today=lambda: dt.date.today().isoformat(),
                 cache_only: bool | None = None, api_key: str | None = None, gate=None):
        """cache_only и api_key задаются явно для одного клиента и не зависят от переменных окружения (на хостинге процесс общий
        для всех посетителей, менять окружение во время работы нельзя): cache_only=None оставляет прежнее поведение (config и
        LLM_CACHE_ONLY), True запрещает вызовы API, False разрешает их даже при LLM_CACHE_ONLY=1 (страница живого ИИ).
        api_key: ключ из st.secrets, иначе из переменной окружения. gate: функция без аргументов, вызывается перед каждым обращением
        к API и возвращает None (можно) или текст причины остановки (сессионный и суточный лимиты сайта, считает вызывающий).
        Лимит времени на прогон: llm.max_run_seconds (отсчёт от создания клиента), по умолчанию нет."""
        env = os.environ if env is None else env
        self.cfg = llm_cfg
        self.model = llm_cfg["model"]
        self.stats = LlmStats()
        self.last_error = None
        self.stop_reason = None              # после этого новых вызовов API нет (кэш по-прежнему читается)
        self.consecutive_429 = 0
        self._key = api_key or env.get(llm_cfg["api_key_env"]) or None
        if cache_only is None:
            self.cache_only = bool(llm_cfg.get("cache_only")) or env.get(llm_cfg.get("cache_only_env", ""), "").lower() in TRUTHY
        else:
            self.cache_only = bool(cache_only)
        self.gate = gate
        cache_dir = env.get(llm_cfg.get("cache_dir_env", "")) or llm_cfg["cache_dir"]
        self.cache = cache or LlmCache(Path(cache_dir) if Path(cache_dir).is_absolute() else root / cache_dir,
                                       write=llm_cfg.get("cache_write", True))
        self._transport = transport
        self.usage = UsageCounter(self.cache.dir / llm_cfg.get("usage_file", "_usage.json"), today,
                                  persist=self.cache.write)
        self.warnings = []
        self._sleep, self._clock = sleep, clock
        self._last_call = None
        self._started = clock()

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

    @property
    def limits(self) -> dict:
        return self.cfg.get("limits", {}).get(self.model) or {}

    @property
    def call_pause(self) -> float:
        """Пауза между вызовами: из конфига или (если null) 60 / rpm * pause_margin по таблице лимитов модели."""
        explicit = self.cfg.get("call_pause_seconds")
        if explicit is not None:
            return float(explicit)
        rpm = self.limits.get("rpm")
        if rpm:
            return 60.0 / rpm * self.cfg.get("pause_margin", 1.25)
        return float(self.cfg.get("fallback_pause_seconds", 5.0))

    def _check_daily_limit(self) -> bool:
        """False: суточный лимит модели исчерпан, прогон останавливается. Иначе при приближении к rpd предупреждение."""
        rpd = self.limits.get("rpd")
        if not rpd:
            return True
        used = self.usage.used(self.model)
        if used >= rpd:
            self.stop_reason = (f"достигнут суточный лимит запросов для {self.model}: {used} из {rpd} "
                                "(по счётчику вызовов), повторите завтра или смените модель")
            return False
        warn = self.cfg.get("rpd_warn_fraction", 0.8)
        if used >= rpd * warn and not self.warnings:
            self.warnings.append(f"суточный лимит {self.model} на исходе: использовано {used} из {rpd} (по счётчику вызовов)")
        return True

    def _pause_between_calls(self) -> None:
        gap = self.call_pause
        if self._last_call is not None and gap:
            wait = gap - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)

    def key_for(self, function: str, prompt_version: str, payload: dict) -> str:
        return cache_key(function, self.model, prompt_version, self.cfg["schema_version"], payload)

    def cached(self, key: str, validate):
        """-> ответ из кэша (прошёл validate) или None. Попадание считается в cache_hits."""
        record = self.cache.get(key)
        if record is not None and validate(record["answer"]):
            self.stats.cache_hits += 1
            return record["answer"]
        return None

    def store(self, key: str, answer, function: str, prompt_version: str, payload: dict) -> None:
        """В кэш идёт только валидный ответ; сбои и «нет ответа» не пишутся."""
        self.cache.put(key, answer, function=function, model=self.model, prompt_version=prompt_version, payload=payload)

    def generate(self, prompt: str, schema: dict, validate):
        """Один запрос к модели с повторами, паузами и счётчиками -> разобранный JSON (прошёл validate) или None.
        Кэш не трогает (его ведёт вызывающий: по запросу или по строке пакета); no_answer не считает."""
        if not self.can_call_api or self.stop_reason:     # «только кэш», нет ключа или прогон остановлен: API не вызываем
            return None
        retries = int(self.cfg["max_retries"])
        for attempt in range(retries + 1):
            if self.stop_reason:
                break
            max_calls = self.cfg.get("max_calls_per_run")
            if max_calls and self.stats.calls >= max_calls:
                self.stop_reason = f"достигнут потолок вызовов за прогон ({max_calls})"
                break
            if not self._check_daily_limit():
                break
            max_seconds = self.cfg.get("max_run_seconds")
            if max_seconds and self._clock() - self._started >= max_seconds:
                self.stop_reason = f"достигнут лимит времени на один прогон ({max_seconds:g} с)"
                break
            if self.gate is not None:
                reason = self.gate()
                if reason:
                    self.stop_reason = self._scrub(reason)
                    break
            self._pause_between_calls()
            self.stats.calls += 1
            self.usage.add(self.model)
            rate_limited, delay = False, None
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
                rate_limited = is_rate_limited(e)
                self.stats.errors += 1
                self.last_error = f"{type(e).__name__}" + (f" {code}" if code else "") + f": {self._scrub(e)[:300]}"
                daily = False
                if rate_limited:
                    self.stats.quota_errors += 1
                    self.consecutive_429 += 1
                    delay, daily = parse_quota_error(e)
                    if daily:
                        self.stop_reason = "суточная квота исчерпана, повторите завтра или смените модель"
                    elif self.consecutive_429 >= int(self.cfg.get("quota_abort_after", 3)):
                        self.stop_reason = (f"{self.consecutive_429} вызова подряд закончились ошибкой 429 (квота): "
                                            "прогон остановлен, повторите позже или смените модель")
                else:
                    self.consecutive_429 = 0
                if self.stop_reason:
                    break
                if attempt < retries:
                    if rate_limited and delay is not None:       # пауза, которую просит сервер (с потолком из конфига)
                        pause = delay
                    else:
                        pause = self.cfg["retry_pause_seconds"] * (2 ** attempt if rate_limited else 1)
                    self._sleep(min(pause, self.cfg["retry_max_pause_seconds"]))
                continue
            self.consecutive_429 = 0
            return answer
        return None

    def ask(self, function: str, prompt_version: str, payload: dict, prompt: str, schema: dict, validate):
        """-> ответ модели (словарь, прошедший validate) или None. payload: нормализованный вход, он идёт в ключ кэша."""
        key = self.key_for(function, prompt_version, payload)
        hit = self.cached(key, validate)
        if hit is not None:
            return hit
        answer = self.generate(prompt, schema, validate)
        if answer is None:
            self.stats.no_answer += 1
            return None
        self.store(key, answer, function, prompt_version, payload)
        return answer
