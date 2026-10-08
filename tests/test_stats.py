"""Тесты агрегатов статистики (`app.services.stats`).

Данные берём за фиксированные месяцы (март/апрель 2024), чтобы результат
не зависел от текущей даты.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.services import stats
from app.timeutils import month_bounds

MARCH = datetime(2024, 3, 10, 12, 0)
APRIL = datetime(2024, 4, 2, 9, 30)
MARCH_START, APRIL_START = month_bounds("2024-03")


@pytest.fixture
def data(session: Session, users, categories, add_expense) -> dict[str, object]:
    """Март: 500 «хлеб» (Слава), 100 «молоко» + 50,5 «taxi» (Маша); апрель: 25 «автобус»."""
    first, second = users
    add_expense(first, categories["Продукты"], 500.0, MARCH, "хлеб")
    add_expense(second, categories["Продукты"], 100.0, MARCH.replace(day=11), "молоко")
    add_expense(second, categories["Транспорт"], 50.5, MARCH.replace(day=20, hour=18), "taxi")
    add_expense(first, categories["Транспорт"], 25.0, APRIL, "автобус")
    return {"first": first, "second": second, "categories": categories}


def test_summary_totals_and_average(session: Session, data) -> None:
    summary = stats.summary(session, MARCH_START, APRIL_START)
    assert summary.total == 650.5
    assert summary.count == 3
    assert summary.days == 31
    assert summary.avg_per_day == pytest.approx(20.98)
    assert (summary.start, summary.end) == (MARCH_START.date(), datetime(2024, 3, 31).date())


def test_summary_filters_by_user(session: Session, data) -> None:
    second = data["second"]
    summary = stats.summary(session, MARCH_START, APRIL_START, user_ids=[second.id])
    assert (summary.total, summary.count) == (150.5, 2)

    by_category = stats.summary(
        session,
        MARCH_START,
        APRIL_START,
        category_ids=[data["categories"]["Продукты"].id],
    )
    assert (by_category.total, by_category.count) == (600.0, 2)


def test_summary_empty_period(session: Session) -> None:
    summary = stats.summary(session, "2020-05-01", "2020-05-02")
    assert (summary.total, summary.count, summary.avg_per_day, summary.days) == (0.0, 0, 0.0, 1)


def test_category_totals_shares(session: Session, data) -> None:
    rows = stats.category_totals(session, MARCH_START, APRIL_START)
    assert [item.name for item in rows] == ["Продукты", "Транспорт"]
    products, transport = rows
    assert (products.total, products.count, products.share) == (600.0, 2, 92.2)
    assert (transport.total, transport.count, transport.share) == (50.5, 1, 7.8)
    assert products.title.startswith("🛒")


def test_category_totals_include_zero(session: Session, data) -> None:
    rows = stats.category_totals(session, MARCH_START, APRIL_START, include_zero=True)
    assert len(rows) == 8
    zero_rows = [item for item in rows if item.total == 0]
    assert len(zero_rows) == 6
    assert all(item.count == 0 for item in zero_rows)


def test_top_categories_limit(session: Session, data) -> None:
    rows = stats.top_categories(session, MARCH_START, APRIL_START, limit=1)
    assert [item.name for item in rows] == ["Продукты"]


def test_daily_totals_fills_empty_days(session: Session, data) -> None:
    rows = stats.daily_totals(session, MARCH_START, APRIL_START)
    assert len(rows) == 31
    assert rows[9].day.day == 10 and rows[9].total == 500.0 and rows[9].count == 1
    assert rows[10].total == 100.0
    assert rows[19].total == 50.5
    assert rows[0].total == 0.0
    assert sum(item.total for item in rows) == 650.5


def test_daily_totals_without_bounds_uses_found_days(session: Session, data) -> None:
    rows = stats.daily_totals(session)
    assert [item.day.day for item in rows] == [10, 11, 20, 2]
    assert rows[-1].total == 25.0


def test_monthly_totals(session: Session, data) -> None:
    rows = stats.monthly_totals(session, months=3, month="2024-04")
    assert [item.month for item in rows] == ["2024-02", "2024-03", "2024-04"]
    assert [item.total for item in rows] == [0.0, 650.5, 25.0]
    assert rows[1].count == 3

def test_user_totals(session: Session, data) -> None:
    rows = stats.user_totals(session, MARCH_START, APRIL_START)
    assert [item.display_name for item in rows] == ["Слава", "Маша"]
    first, second = rows
    assert (first.total, first.count, first.share) == (500.0, 1, 76.9)
    assert (second.total, second.count, second.share) == (150.5, 2, 23.1)


def test_compare_periods(session: Session, data) -> None:
    comparison = stats.compare_periods(session, MARCH_START, APRIL_START)
    assert comparison.current_total == 650.5
    assert comparison.previous_total == 0.0
    assert comparison.delta == 650.5
    assert comparison.delta_percent is None


def test_available_months(session: Session, data) -> None:
    assert stats.available_months(session) == ["2024-04", "2024-03"]


def test_fetch_expenses_ordering_and_filters(session: Session, data) -> None:
    first, second = data["first"], data["second"]
    categories = data["categories"]

    newest = stats.fetch_expenses(session)
    assert [item.amount for item in newest] == [25.0, 50.5, 100.0, 500.0]
    assert newest[0].category.name == "Транспорт"

    assert [item.amount for item in stats.fetch_expenses(session, limit=2)] == [25.0, 50.5]
    assert [item.amount for item in stats.fetch_expenses(session, offset=2)] == [100.0, 500.0]

    assert [item.comment for item in stats.fetch_expenses(session, search="ХЛЕБ")] == ["хлеб"]
    assert [item.comment for item in stats.fetch_expenses(session, search="taxi")] == ["taxi"]
    assert stats.fetch_expenses(session, search="нет-такого") == []

    assert len(stats.fetch_expenses(session, user_ids=[first.id])) == 2
    assert len(stats.fetch_expenses(session, start=MARCH_START, end=APRIL_START)) == 3
    assert len(stats.fetch_expenses(session, category_ids=[categories["Продукты"].id])) == 2
    assert (
        len(
            stats.fetch_expenses(
                session, user_ids=[second.id], start=MARCH_START, end=APRIL_START
            )
        )
        == 2
    )


def test_total_amount(session: Session, data) -> None:
    assert stats.total_amount(session, start=MARCH_START, end=APRIL_START) == 650.5
    assert stats.total_amount(session, start=MARCH_START, end=APRIL_START, search="хлеб") == 500.0
    assert stats.total_amount(session, start=datetime(2020, 1, 1), end=datetime(2021, 1, 1)) == 0.0


def test_recent_expenses_limit(session: Session, data) -> None:
    assert len(stats.recent_expenses(session, limit=2)) == 2
    assert stats.recent_expenses(session, limit=1)[0].comment == "автобус"


def test_expenses_out_is_pydantic(session: Session, data) -> None:
    items = stats.expenses_out(session, limit=1)
    assert items[0].category.name == "Транспорт"
    assert items[0].user.display_name == "Слава"
    assert items[0].currency == "BYN"
    assert items[0].model_dump()["amount"] == 25.0


def test_as_datetime_and_inclusive_end_helpers() -> None:
    assert stats.as_datetime("") is None
    assert stats.as_datetime(None) is None
    assert stats.as_datetime("2024-03-10") == datetime(2024, 3, 10)
    assert stats.as_datetime(datetime(2024, 3, 10, 15, 0)) == datetime(2024, 3, 10, 15, 0)
    assert stats.inclusive_end("2024-03-10") == datetime(2024, 3, 11)
    assert stats.inclusive_end(None) is None
