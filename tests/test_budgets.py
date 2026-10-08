"""Тесты бюджетов (`app.services.budgets`)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy.orm import Session

from app.services import budgets
from app.timeutils import month_key


def test_upsert_creates_and_updates(session: Session) -> None:
    created = budgets.upsert_budget(session, "2024-03", 1000.0)
    session.commit()
    assert created is not None
    assert created.month == "2024-03"
    assert created.category_id is None
    assert created.limit_amount == 1000.0

    updated = budgets.upsert_budget(session, "2024-03", 1200.0)
    session.commit()
    assert updated.id == created.id
    assert [item.limit_amount for item in budgets.list_budgets(session, "2024-03")] == [1200.0]


def test_upsert_accepts_dates_and_zero_removes(session: Session, categories) -> None:
    created = budgets.upsert_budget(session, date(2024, 3, 15), 300.0, categories["Кафе"].id)
    assert created.month == "2024-03"

    assert budgets.upsert_budget(session, "2024-03", 0, categories["Кафе"].id) is None
    assert budgets.get_budget(session, "2024-03", categories["Кафе"].id) is None
    assert budgets.list_budgets(session, "2024-03") == []


def test_list_budgets_overall_first(session: Session, categories) -> None:
    budgets.upsert_budget(session, "2024-03", 500.0, categories["Продукты"].id)
    budgets.upsert_budget(session, "2024-03", 2000.0)
    budgets.upsert_budget(session, "2024-04", 3000.0)
    session.commit()

    rows = budgets.list_budgets(session, "2024-03")
    assert [item.category_id for item in rows] == [None, categories["Продукты"].id]
    assert budgets.list_budgets(session, datetime(2024, 4, 5))[0].limit_amount == 3000.0


def test_save_budgets_mass_update(session: Session, categories) -> None:
    saved = budgets.save_budgets(
        session,
        "2024-03",
        {None: 1000.0, categories["Продукты"].id: 400.0, categories["Кафе"].id: 0.0},
    )
    session.commit()
    assert saved == 2
    assert len(budgets.list_budgets(session, "2024-03")) == 2


def test_delete_budget(session: Session) -> None:
    created = budgets.upsert_budget(session, month_key(), 100.0)
    session.commit()
    assert budgets.delete_budget(session, created.id) is True
    assert budgets.delete_budget(session, created.id) is False


def test_budget_progress(session: Session, user, categories, add_expense) -> None:
    add_expense(user, categories["Продукты"], 300.0, datetime(2024, 3, 5, 10, 0))
    add_expense(user, categories["Транспорт"], 25.0, datetime(2024, 3, 6, 10, 0))
    budgets.upsert_budget(session, "2024-03", 1000.0)
    budgets.upsert_budget(session, "2024-03", 400.0, categories["Продукты"].id)
    session.commit()

    progress = budgets.budget_progress(session, "2024-03")
    assert [item.category_id for item in progress] == [None, categories["Продукты"].id]

    overall = progress[0]
    assert (overall.spent, overall.limit_amount, overall.remaining) == (325.0, 1000.0, 675.0)
    assert (overall.percent, overall.over) == (32.5, False)
    assert overall.category_name == "Всё вместе" and overall.emoji == "🎯"

    by_category = progress[1]
    assert (by_category.spent, by_category.limit_amount, by_category.remaining) == (300.0, 400.0, 100.0)
    assert (by_category.percent, by_category.over) == (75.0, False)
    assert by_category.category_name == "Продукты" and by_category.emoji == "🛒"


def test_budget_progress_flags_over_limit(session: Session, user, categories, add_expense) -> None:
    add_expense(user, categories["Продукты"], 300.0, datetime(2024, 3, 5, 10, 0))
    budgets.upsert_budget(session, "2024-03", 100.0)
    session.commit()

    overall = budgets.overall_progress(session, "2024-03")
    assert overall is not None
    assert overall.over is True
    assert overall.remaining == -200.0
    assert overall.percent == 300.0


def test_budget_progress_uses_default_category_name_when_no_spending(
    session: Session, categories
) -> None:
    """Если по категории ещё не тратили — имя берём из справочника."""
    budgets.upsert_budget(session, "2024-03", 200.0, categories["Здоровье"].id)
    session.commit()

    progress = budgets.budget_progress(session, "2024-03")[0]
    assert progress.category_name == "Здоровье"
    assert progress.spent == 0.0
    assert progress.percent == 0.0


def test_overall_and_remaining_for(session: Session, user, categories, add_expense) -> None:
    assert budgets.overall_progress(session, "2024-03") is None
    assert budgets.remaining_for(session, "2024-03") is None

    add_expense(user, categories["Кафе"], 60.0, datetime(2024, 3, 7, 10, 0))
    budgets.upsert_budget(session, "2024-03", 500.0)
    session.commit()
    assert budgets.remaining_for(session, "2024-03") == 440.0


@pytest.mark.parametrize("month", ["2024-03", date(2024, 3, 20), datetime(2024, 3, 20, 5, 0)])
def test_month_argument_types(session: Session, month) -> None:
    budgets.upsert_budget(session, month, 10.0)
    session.commit()
    assert budgets.remaining_for(session, month) == 10.0
