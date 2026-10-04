"""ИИ-слой на Gemini: клиент с кэшем и запасным путём, судья пар. Подробности: docs/synthetic_spec.md §10."""
from .cache import LlmCache
from .client import LlmClient, LlmStats
from .pair_judge import GeminiPairJudge

AI_COUNTERS = ("calls", "errors", "cache_hits", "no_answer", "low_confidence", "rejected_by_check", "quota_errors")


def build_default_ai(cfg: dict):
    """-> (judge, row_matcher) для run_pipeline(mode="llm"), если вызывающий ничего не передал.
    Судья возвращается всегда; доступность (ключ есть или кэш найден) он сообщает сам через .available."""
    client = LlmClient(cfg["rules"]["llm"])
    judge = GeminiPairJudge(client, cfg) if cfg["rules"]["llm"]["functions"].get("matching") else None
    return judge, None


__all__ = ["LlmCache", "LlmClient", "LlmStats", "GeminiPairJudge", "build_default_ai", "AI_COUNTERS"]
