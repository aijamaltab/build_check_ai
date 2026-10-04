"""ИИ-слой на Gemini: клиент с кэшем и запасным путём, судья пар. Подробности: docs/synthetic_spec.md §10."""
from .cache import LlmCache
from .client import LlmClient, LlmStats
from .pair_judge import GeminiPairJudge
from .row_matcher import GeminiRowMatcher

AI_COUNTERS = ("calls", "errors", "cache_hits", "no_answer", "low_confidence", "rejected_by_check", "quota_errors")


def build_default_ai(cfg: dict, cache_only: bool = False):
    """-> (judge, row_matcher) для run_pipeline(mode="llm"), если вызывающий ничего не передал.
    Оба делят один клиент (кэш, счётчики, остановка по квоте). Доступность (ключ есть или кэш найден) они сообщают сами
    через .available. cache_only=True: API не вызывается даже при ключе в окружении (оценка по кэшу)."""
    llm = {**cfg["rules"]["llm"], "cache_only": True} if cache_only else cfg["rules"]["llm"]
    client = LlmClient(llm)
    functions = cfg["rules"]["llm"]["functions"]
    judge = GeminiPairJudge(client, cfg) if functions.get("matching") else None
    row_matcher = GeminiRowMatcher(client, cfg) if functions.get("row_matching") else None
    return judge, row_matcher


__all__ = ["LlmCache", "LlmClient", "LlmStats", "GeminiPairJudge", "GeminiRowMatcher", "build_default_ai", "AI_COUNTERS"]
