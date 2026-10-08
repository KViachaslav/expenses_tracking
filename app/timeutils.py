"""Работа с датами и локальным часовым поясом.

Время хранится в БД в виде naive-datetime в локальном поясе (`TZ` из .env,
по умолчанию Europe/Minsk) — так проще строить отчёты «за сегодня/месяц»
и не путаться с переводами времени.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import settings

TZ = ZoneInfo(settings.tz)

MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
MONTHS_RU_NOMINATIVE = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)


# --------------------------------------------------------------------------- #
# «Сейчас» в локальном поясе
# --------------------------------------------------------------------------- #
def local_now() -> datetime:
    """Текущее локальное время (naive, без tzinfo)."""
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return local_now().date()


# --------------------------------------------------------------------------- #
# Границы периодов. `end` — всегда исключающая граница (start <= x < end)
# --------------------------------------------------------------------------- #
def to_datetime(value: date | datetime | str | None) -> datetime | None:
    """Приводит дату/строку/дату-время к datetime (дата -> начало дня)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Не удалось разобрать дату: {value!r}")


def to_date(value: date | datetime | str | None) -> date | None:
    parsed = to_datetime(value)
    return parsed.date() if parsed else None


def day_bounds(day: date | datetime | str | None = None) -> tuple[datetime, datetime]:
    """Границы суток: (00:00 дня, 00:00 следующего дня)."""
    current = to_date(day) or today()
    start = datetime(current.year, current.month, current.day)
    return start, start + timedelta(days=1)


def days_bounds(day: date | datetime | str | None, days: int) -> tuple[datetime, datetime]:
    """Границы периода из `days` дней, заканчивающегося указанным днём (включительно)."""
    current = to_date(day) or today()
    end = datetime(current.year, current.month, current.day) + timedelta(days=1)
    start = datetime(current.year, current.month, current.day) - timedelta(days=max(days, 1) - 1)
    return start, end


def current_month() -> str:
    """Ключ текущего (локального) месяца 'YYYY-MM'."""
    now = local_now()
    return f"{now.year:04d}-{now.month:02d}"


def parse_month(value: str | date | datetime | None, default: str | None = None) -> str:
    """Приводит значение к ключу месяца 'YYYY-MM'.

    Пустое значение -> `default`, а если он не задан — текущий месяц.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return default or current_month()
    if isinstance(value, datetime):
        return f"{value.year:04d}-{value.month:02d}"
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}"
    text = str(value).strip()
    for fmt in ("%Y-%m", "%Y-%m-%d", "%m.%Y", "%Y.%m"):
        try:
            parsed = datetime.strptime(text, fmt)
            return f"{parsed.year:04d}-{parsed.month:02d}"
        except ValueError:
            continue
    raise ValueError(f"Не удалось разобрать месяц: {value!r}")


def month_key(value: date | datetime | str | None = None) -> str:
    """Ключ месяца для текущей (или переданной) даты."""
    return parse_month(value)


def month_bounds(month: str | date | datetime | None = None) -> tuple[datetime, datetime]:
    """Границы месяца: (1-е число 00:00, 1-е число следующего месяца 00:00)."""
    key = parse_month(month)
    year, mon = int(key[:4]), int(key[5:7])
    start = datetime(year, mon, 1)
    if mon == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, mon + 1, 1)
    return start, end


def previous_month_bounds(month: str | date | datetime | None = None) -> tuple[datetime, datetime]:
    return month_bounds(shift_month(month, -1))


def shift_month(month: str | date | datetime | None, delta: int) -> str:
    """Сдвигает месяц на `delta` месяцев и возвращает ключ 'YYYY-MM'."""
    key = parse_month(month)
    year, mon = int(key[:4]), int(key[5:7])
    total = year * 12 + (mon - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def last_months(count: int, month: str | date | datetime | None = None) -> list[str]:
    """Список последних `count` месяцев (включая указанный), по возрастанию."""
    key = parse_month(month)
    return [shift_month(key, -delta) for delta in range(count - 1, -1, -1)]


def month_label(month: str | date | datetime | None = None) -> str:
    """'2025-01' -> 'Январь 2025'."""
    key = parse_month(month)
    year, mon = int(key[:4]), int(key[5:7])
    return f"{MONTHS_RU_NOMINATIVE[mon - 1]} {year}"


def month_days(month: str | date | datetime | None = None) -> int:
    key = parse_month(month)
    return monthrange(int(key[:4]), int(key[5:7]))[1]


def date_series(start: date, end_inclusive: date) -> list[date]:
    """Все даты от start до end включительно."""
    if end_inclusive < start:
        return []
    return [start + timedelta(days=offset) for offset in range((end_inclusive - start).days + 1)]


def period_days(start: datetime, end: datetime) -> int:
    """Количество суток в периоде [start, end)."""
    return max((to_date(end) - to_date(start)).days, 1)  # type: ignore[operator]
