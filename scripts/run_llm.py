#!/usr/bin/env python
"""Прогон на data/synthetic с настоящим Gemini и запись ответов в кэш data/cache/llm/ (запускать вручную, нужен ключ).

  $env:GEMINI_API_KEY = "..."      # PowerShell, только в этом окне; ключ нигде не печатается и не пишется
  python scripts/run_llm.py
  python scripts/run_llm.py --cache-only    # повторный прогон только по кэшу: API не вызывается, ключ не нужен

Печатает число вызовов, ошибок, попаданий в кэш, ответов «нет ответа» и время. Закоммитить после прогона нужно
data/cache/llm/ (синтетика, секретов там нет), чтобы демо шло в режиме llm без ключа.
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
    args = parser.parse_args(argv)
    if args.cache_only:
        os.environ[llm["cache_only_env"]] = "1"
    elif not os.environ.get(llm["api_key_env"]):
        print(f"Переменная окружения {llm['api_key_env']} не задана. Задайте её в этом окне "
              f"или запустите с --cache-only (только по кэшу).")
        return 1

    judge, row_matcher = build_default_ai(cfg)
    started = time.perf_counter()
    summary = run_pipeline(args.source, args.db, "llm", judge, row_matcher, cfg=cfg)
    elapsed = time.perf_counter() - started
    if summary["banner"]:
        print(f"[!] {summary['banner']} (запрошен режим llm)")
    print(summary["text"])
    ai = summary["ai"]
    print(f"\nИИ: пар отправлено судье {ai['pairs_asked']}, принято {ai['pairs_accepted']}")
    print("Счётчики: " + ", ".join(f"{name} {ai[name]}" for name in AI_COUNTERS))
    client = getattr(judge, "client", None)
    if client is not None and client.last_error:
        print("Последняя ошибка API (ключ вырезан):", client.last_error)
    print(f"Время: {elapsed:.1f} с; режим {summary['mode']}; кэш {client.cache.dir if client else '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
