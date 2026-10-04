#!/usr/bin/env python
"""Прогон на data/synthetic с настоящим Gemini и запись ответов в кэш data/cache/llm/ (запускать вручную, нужен ключ).

  $env:GEMINI_API_KEY = "..."      # PowerShell, только в этом окне; ключ нигде не печатается и не пишется
  python scripts/run_llm.py
  python scripts/run_llm.py --pause 6 --max-calls 40 --model gemini-2.5-flash-lite
  python scripts/run_llm.py --cache-only    # повторный прогон только по кэшу: API не вызывается, ключ не нужен

Печатает число вызовов, ошибок, попаданий в кэш, ответов «нет ответа» и время. Ошибки и «нет ответа» в кэш не пишутся,
поэтому после остановки по квоте можно просто запустить скрипт снова: уже полученные ответы возьмутся из кэша.
Закоммитить после полного прогона нужно data/cache/llm/ (синтетика, секретов там нет).
"""
import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config  # noqa: E402
from src.llm import AI_COUNTERS, build_default_ai  # noqa: E402
from src.pipeline import run_pipeline  # noqa: E402


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    llm = cfg["rules"]["llm"]
    parser = argparse.ArgumentParser(description="Прогон data/synthetic в режиме llm (настоящий Gemini + кэш)")
    parser.add_argument("--source", default=str(ROOT / "data" / "synthetic"))
    parser.add_argument("--db", default=str(ROOT / "data" / "cache" / "demo.db"))
    parser.add_argument("--cache-only", action="store_true", help="только кэш, без вызовов API и без ключа")
    parser.add_argument("--pause", type=float, default=None, help="пауза между вызовами, с (по умолчанию 60 / rpm * запас по таблице limits для модели)")
    parser.add_argument("--max-calls", type=int, default=None, help="потолок вызовов к API за прогон")
    parser.add_argument("--model", default=None, help=f"модель на этот прогон (в конфиге {llm['model']})")
    args = parser.parse_args(argv)
    if args.pause is not None:
        llm["call_pause_seconds"] = args.pause
    if args.max_calls is not None:
        llm["max_calls_per_run"] = args.max_calls
    if args.model:
        llm["model"] = args.model                       # модель входит в ключ кэша: у другой модели свой кэш
    if args.cache_only:
        os.environ[llm["cache_only_env"]] = "1"
    elif not os.environ.get(llm["api_key_env"]):
        print(f"Переменная окружения {llm['api_key_env']} не задана. Задайте её в этом окне "
              f"или запустите с --cache-only (только по кэшу).")
        return 1

    judge, row_matcher = build_default_ai(cfg)
    client = getattr(judge, "client", None)
    if client is not None:
        limits = client.limits
        print(f"Модель {client.model}: пауза {client.call_pause:.1f} с"
              + (f", лимиты rpm {limits.get('rpm')}, rpd {limits.get('rpd') or 'неизвестен'} (предварительные цифры)" if limits else
                 ", лимиты модели в config не заданы")
              + f"; вызовов сегодня уже {client.usage.used(client.model)}")
    started = time.perf_counter()
    summary = run_pipeline(args.source, args.db, "llm", judge, row_matcher, cfg=cfg)
    elapsed = time.perf_counter() - started
    if summary["banner"]:
        print(f"[!] {summary['banner']} (запрошен режим llm)")
    print(summary["text"])
    ai = summary["ai"]
    print(f"\nИИ (модель {llm['model']}): пар отправлено судье {ai['pairs_asked']}, принято {ai['pairs_accepted']}, без решения {ai['pairs_no_decision']}")
    print(f"RowMatcher: строк отправлено {ai['rows_asked']}, принято {ai['rows_accepted']}, подтверждено «в ВОР нет» {ai['rows_none']}, "
          f"отклонено кодом {ai['rows_rejected'] - ai['rows_no_decision']}, без решения {ai['rows_no_decision']}")
    print("Счётчики: " + ", ".join(f"{name} {ai[name]}" for name in AI_COUNTERS))
    for warning in ai["warnings"]:
        print("[!]", warning)
    if client is not None and client.last_error:
        print("Последняя ошибка API (ключ вырезан):", client.last_error)
    incomplete = bool(ai["quota_errors"] or ai["no_answer"] or ai["stop_reason"] or ai["pairs_no_decision"] or ai["rows_no_decision"])
    if ai["stop_reason"]:
        print(f"\n[!] ПРОГОН ОСТАНОВЛЕН: {ai['stop_reason']}.")
    if ai["pairs_asked"] or ai["rows_asked"]:
        print(f"Пар разобрано {ai['pairs_asked'] - ai['pairs_no_decision']} из {ai['pairs_asked']}, осталось {ai['pairs_no_decision']}; "
              f"строк разобрано {ai['rows_asked'] - ai['rows_no_decision']} из {ai['rows_asked']}, осталось {ai['rows_no_decision']}. "
              "Полученные ответы сохранены в кэш; повторный запуск возьмёт их из кэша.")
    print(f"Время: {elapsed:.1f} с; режим {summary['mode']}; кэш {client.cache.dir if client else '-'}")
    if incomplete:
        print("ПРОГОН НЕПОЛНЫЙ, ЦИФРЫ НЕ ИСПОЛЬЗОВАТЬ (были ошибки квоты или пары без ответа).")
    return 2 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
