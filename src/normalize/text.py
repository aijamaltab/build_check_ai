"""Нормализация названий, чисел и дат."""
import datetime as dt
import re


def normalize_name(name, strip_markers=()) -> str:
    """lower, ё -> е, убрать маркеры (/прим/), схлопнуть пробелы. Скобки не удаляем."""
    s = str(name).lower().replace("ё", "е")
    for marker in strip_markers:
        s = s.replace(marker.lower().replace("ё", "е"), " ")
    return re.sub(r"\s+", " ", s).strip()


def normalize_header(cell) -> str:
    """Заголовок колонки для сравнения: lower, ё -> е, схлопнутые пробелы."""
    return re.sub(r"\s+", " ", str(cell).lower().replace("ё", "е")).strip()


def parse_number(value):
    """Число из ячейки: 12,5 и 12.5 и «1 200,5» -> float. Не число -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", s):
        return None
    return float(s)


def parse_date(value):
    """Дата из ячейки (datetime/date или текст ДД.ММ.ГГГГ / ГГГГ-ММ-ДД) -> date; иначе None."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if value is None:
        return None
    s = str(value).strip()
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    try:
        if m:
            return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return dt.date.fromisoformat(s)
    except ValueError:
        return None
    return None


def find_date_in_text(text, regex):
    """Дата по регулярному выражению из шаблона (doc_date_regex), например «от 30.06.2025»."""
    m = re.search(regex, str(text))
    return parse_date(m.group(1)) if m else None
