"""Минимальные dq-проверки (CLAUDE.md §8). Каждая проверка пишет одну запись в dq_checks по документу.

Файл, не прошедший хотя бы одну проверку, получает documents.status = error: он не участвует в анализе молча.
Пороги берутся из config/rules.yaml (data_quality, formulas).
"""
from collections import Counter
from dataclasses import dataclass

MAX_LISTED = 10     # сколько строк перечислять в details


@dataclass
class DQResult:
    check_name: str
    passed: bool
    details: str = ""


def _rows(nums) -> str:
    nums = list(nums)
    tail = f" и ещё {len(nums) - MAX_LISTED}" if len(nums) > MAX_LISTED else ""
    return "строки " + ", ".join(map(str, nums[:MAX_LISTED])) + tail


def run_checks(doc, items, cfg: dict) -> list:
    dq, rules = [], cfg["rules"]
    parsed_ok = not doc.errors
    dq.append(DQResult("документ разобран", parsed_ok, "; ".join(doc.errors)))
    if not parsed_ok or doc.contract is not None:
        return dq

    neg = [i.source_row for i in items if i.quantity is not None and i.quantity < 0]
    dq.append(DQResult("количество не отрицательное", not neg, _rows(neg) if neg else ""))

    unknown = [i for i in items if not i.unit_ok]
    dq.append(DQResult("единица известна", not unknown,
                       "; ".join(f"строка {i.source_row}: {i.unit_reason}" for i in unknown[:MAX_LISTED])))

    # полный дубль = совпали название, единица, количество и формула. Повтор названия с другим количеством не дубль.
    def dup_key(i):
        key = (i.name_norm, i.unit_raw, i.quantity_raw, i.formula_raw)
        return key + (i.amount,) if doc.allow_repeated_names else key     # у актов с «суммой первичной» учитываем и сумму

    counts = Counter(dup_key(i) for i in items)
    dups = [i.source_row for i in items if counts[dup_key(i)] > 1]
    dq.append(DQResult("нет полных дублей строк", not dups, _rows(dups) if dups else ""))

    total_ok, details = True, "итога в документе нет"
    if doc.total_amount is not None and doc.has_amount_column:
        s = sum(i.amount for i in items if i.amount is not None)
        tol = abs(doc.total_amount) * rules["data_quality"]["sum_tolerance_pct"] / 100
        total_ok = abs(s - doc.total_amount) <= tol
        details = f"сумма строк {s:.2f}, итог в документе {doc.total_amount:.2f} (строка {doc.total_row})"
    dq.append(DQResult("сумма строк равна итогу", total_ok, details))

    n_bad, n_all = len(doc.unrecognized), len(items) + len(doc.unrecognized)
    share = n_bad / n_all if n_all else 0.0
    limit = rules["data_quality"]["max_unrecognized_share"]
    listed = "; ".join(f"строка {r}: {why}" for r, why in doc.unrecognized[:MAX_LISTED])
    dq.append(DQResult("доля нераспознанных строк", share <= limit,
                       f"не распознано {n_bad} из {n_all}" + (f"; {listed}" if n_bad else "")))

    dq.append(DQResult(rules["formulas"]["missing_value_dq_check"], not doc.formula_missing,
                       _rows(doc.formula_missing) if doc.formula_missing else ""))
    return dq
