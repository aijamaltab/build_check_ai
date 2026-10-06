"""Лимиты живых запросов к API для публичной страницы: на сессию и на сутки по всему сайту.

Счётчики только в памяти процесса (потокобезопасно): на хостинге процесс один на всех посетителей. Суточный счётчик дополнительно
сверяется со служебным _usage.json клиента (берётся большее из двух), чтобы перезапуск сессии не обнулял расход.
Секретов здесь нет: ключ API сюда не попадает.
"""
import datetime as dt
import threading


class CallBudget:
    """Лимит числа вызовов. daily=True: счётчик обнуляется при смене даты (местное время)."""

    def __init__(self, limit: int, *, daily: bool = False, today=lambda: dt.date.today().isoformat()):
        self.limit, self.daily, self._today = int(limit), daily, today
        self._day = today()
        self._count = 0
        self._extra = lambda: 0
        self._lock = threading.Lock()

    def attach_usage(self, used) -> None:
        """used: функция без аргументов -> число вызовов за сегодня из другого источника (например UsageCounter клиента)."""
        self._extra = used

    def _roll(self) -> None:
        if self.daily and self._today() != self._day:
            self._day, self._count = self._today(), 0

    @property
    def used(self) -> int:
        with self._lock:
            self._roll()
            return max(self._count, int(self._extra() or 0)) if self.daily else self._count

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def take(self) -> bool:
        """Занять один вызов: False, если лимит исчерпан (счётчик не растёт)."""
        with self._lock:
            self._roll()
            used = max(self._count, int(self._extra() or 0)) if self.daily else self._count
            if used >= self.limit:
                return False
            self._count = used + 1
            return True


def make_gate(session: CallBudget, site: CallBudget):
    """-> gate() для LlmClient: None, если вызов разрешён (и он записан в оба счётчика), иначе человекочитаемая причина остановки."""
    def gate():
        if session.remaining <= 0:
            return f"достигнут лимит живых ИИ-запросов для вашей сессии ({session.limit})"
        if site.remaining <= 0:
            return f"достигнут общий суточный лимит живых ИИ-запросов сайта ({site.limit}), повторите завтра"
        if not site.take():
            return f"достигнут общий суточный лимит живых ИИ-запросов сайта ({site.limit}), повторите завтра"
        session.take()
        return None
    return gate
