"""Живой ИИ на странице «Проверить свои файлы»: ключ, лимиты, сборка судей и тексты о режиме. Без Streamlit, чтобы тестировать без браузера.

Ключ берётся только из secrets хостинга (st.secrets["GEMINI_API_KEY"]) или переменной окружения GEMINI_API_KEY, живёт только в памяти
на время прогона и не попадает в session_state, кэш, логи и тексты ошибок (scrub). Остальные страницы остаются на кэше
(cache_only=True по умолчанию, режим задаётся клиенту явно, окружение не меняется).
Лимиты ниже выбраны под бесплатный тариф (gemini-3.1-flash-lite: 15 запросов в минуту, 500 в сутки по предварительной таблице limits).
"""
import os

from src.llm import build_default_ai
from src.llm.budget import CallBudget, make_gate

KEY_NAME = "GEMINI_API_KEY"
SESSION_LIMIT = 25        # живых запросов на одну сессию посетителя
SITE_DAILY_LIMIT = 150    # живых запросов в сутки на весь сайт (из 500 в сутки по таблице limits модели)
RUN_SECONDS = 90          # время на один прогон, с
MAX_FILES = 9            # столько файлов в демо-наборе (ВОР 2, смета, договор, акты 5)
MAX_FILE_MB = 5
EXTRA_OVERRIDES: dict = {}   # только для тестов: например {"call_pause_seconds": 0}, чтобы фейковый клиент не ждал паузу по rpm
PRIVACY_WARNING = ("Для своих файлов используйте обезличенные документы, без коммерческой тайны: названия работ из них отправляются "
                   "во внешний сервис ИИ (Gemini). Демо-наборы никуда не отправляются.")


def get_api_key(secrets=None, env=None) -> str | None:
    """Ключ из secrets (объект с .get и возможными ошибками при отсутствии файла) или из окружения; None, если ключа нет."""
    env = os.environ if env is None else env
    try:
        value = secrets.get(KEY_NAME) if secrets is not None else None
    except Exception:  # noqa: BLE001: нет файла secrets или он не читается: это «ключа нет», а не ошибка страницы
        value = None
    return (str(value).strip() if value else "") or (env.get(KEY_NAME) or "").strip() or None


def scrub(text, key: str | None) -> str:
    """Текст без ключа (для сообщений об ошибках)."""
    text = str(text)
    return text.replace(key, "***") if key else text


def build_live_ai(cfg: dict, api_key: str | None, session: CallBudget, site: CallBudget, progress=None):
    """-> (judge, row_matcher, live). Ключ есть: API разрешён явно (cache_only=False) с лимитами; нет ключа: только кэш."""
    live = bool(api_key)
    overrides = {"max_run_seconds": RUN_SECONDS, **EXTRA_OVERRIDES} if live else None
    gate = make_gate(session, site) if live else None
    judge, row_matcher = build_default_ai(cfg, cache_only=not live, api_key=api_key, llm_overrides=overrides, gate=gate, progress=progress)
    client = getattr(judge, "client", None) or getattr(row_matcher, "client", None)
    if client is not None:
        site.attach_usage(lambda: client.usage.used(client.model))
    return judge, row_matcher, live


def describe_ai(summary: dict, live: bool) -> dict:
    """Тексты для страницы: строка о режиме и (если прогон остановлен) объяснение «что сделано, что осталось, почему»."""
    ai = summary.get("ai", {})
    calls, hits = int(ai.get("calls", 0)), int(ai.get("cache_hits", 0))
    line = f"ИИ: новых запросов {calls}, из сохранённых ответов {hits}."
    if not live:
        line += " Ключ ИИ не настроен: для новых названий живые запросы не выполнялись."
    stop = ai.get("stop_reason")
    left_pairs, left_rows = int(ai.get("pairs_no_decision", 0)), int(ai.get("rows_no_decision", 0))
    stopped = None
    if stop:
        done_pairs = int(ai.get("pairs_asked", 0)) - left_pairs
        done_rows = int(ai.get("rows_asked", 0)) - left_rows
        stopped = (f"Разбор остановлен: {stop}. Разобрано пар названий {done_pairs} из {ai.get('pairs_asked', 0)}, "
                   f"строк без пары {done_rows} из {ai.get('rows_asked', 0)}; осталось пар {left_pairs}, строк {left_rows}. "
                   "Оставшиеся позиции показаны как неоднозначные и требуют проверки вручную. Ответы, уже полученные от ИИ, сохранены.")
    elif left_pairs or left_rows:
        stopped = (f"Для части названий ответа ИИ нет: пар {left_pairs}, строк {left_rows}. "
                   "Эти позиции показаны как неоднозначные и требуют проверки вручную.")
    return {"line": line, "stopped": stopped}
