"""Тесты модуля работы с датами (`app.timeutils`)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.timeutils import (
    date_series,
    day_bounds,
    days_bounds,
    last_months,
    local_now,
    month_bounds,
    month_days,
    month_key,
    month_label,
    parse_month,
    period_days,
    previous_month_bounds,
    shift_month,
    to_date,
    to_datetime,
)


def test_local_now_is_naive_and_rounded() -> None:
    now = local_now()
    assert now.tzinfo is None
    assert now.microsecond == 0


def test_month_key_accepts_different_formats() -> None:
    assert month_key("2025-01") == "2025-01"
    assert month_key("01.2025") == "2025-01"
    assert month_key("2025.01") == "2025-01"
    assert month_key("2025-01-31") == "2025-01"
    assert month_key(date(2025, 3, 5)) == "2025-03"
    assert month_key(datetime(2025, 3, 5, 10, 30)) == "2025-03"


def test_parse_month_empty_uses_default() -> None:
    assert parse_month(None, "2024-02") == "2024-02"
    assert parse_month("   ", "2024-02") == "2024-02"
    assert parse_month("") == month_key()


def test_parse_month_invalid_raises() -> None:
    with pytest.raises(ValueError):
        parse_month("не-месяц")


def test_month_bounds_and_year_rollover() -> None:
    assert month_bounds("2025-05") == (datetime(2025, 5, 1), datetime(2025, 6, 1))
    assert month_bounds("2025-12") == (datetime(2025, 12, 1), datetime(2026, 1, 1))


def test_previous_month_bounds_crosses_year() -> None:
    assert previous_month_bounds("2025-01") == (datetime(2024, 12, 1), datetime(2025, 1, 1))


def test_shift_month_forward_and_back() -> None:
    assert shift_month("2024-01", -1) == "2023-12"
    assert shift_month("2024-12", 2) == "2025-02"
    assert shift_month("2024-06", 0) == "2024-06"


def test_last_months() -> None:
    assert last_months(3, "2025-01") == ["2024-11", "2024-12", "2025-01"]
    assert last_months(1, "2025-01") == ["2025-01"]


def test_month_label_and_days() -> None:
    assert month_label("2025-01") == "Январь 2025"
    assert month_label("2025-12") == "Декабрь 2025"
    assert month_days("2024-02") == 29
    assert month_days("2025-02") == 28


def test_to_datetime_formats() -> None:
    assert to_datetime("31.01.2025") == datetime(2025, 1, 31)
    assert to_datetime("2025-01-31") == datetime(2025, 1, 31)
    assert to_datetime("2025-01-31T15:30") == datetime(2025, 1, 31, 15, 30)
    assert to_datetime(date(2025, 1, 31)) == datetime(2025, 1, 31)
    assert to_datetime(None) is None


def test_to_datetime_invalid_raises() -> None:
    with pytest.raises(ValueError):
        to_datetime("не дата")


def test_to_date() -> None:
    assert to_date("2025-01-31T15:30") == date(2025, 1, 31)
    assert to_date(None) is None


def test_day_bounds() -> None:
    assert day_bounds("2025-01-31") == (datetime(2025, 1, 31), datetime(2025, 2, 1))


def test_days_bounds() -> None:
    start, end = days_bounds("2025-01-31", 3)
    assert start == datetime(2025, 1, 29)
    assert end == datetime(2025, 2, 1)


def test_date_series() -> None:
    assert date_series(date(2025, 1, 1), date(2025, 1, 3)) == [
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2025, 1, 3),
    ]
    assert date_series(date(2025, 1, 3), date(2025, 1, 1)) == []


def test_period_days_never_zero() -> None:
    assert period_days(datetime(2025, 1, 1), datetime(2025, 2, 1)) == 31
    assert period_days(datetime(2025, 1, 1), datetime(2025, 1, 1)) == 1
