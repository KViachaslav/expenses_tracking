"""Тесты сервиса расходов и пользователей (`app.services.expenses`)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services import expenses as expenses_service
from app.timeutils import local_now


def test_ensure_user_creates_and_updates(session: Session) -> None:
    created = expenses_service.ensure_user(session, 42, username="first", full_name="Первый")
    session.commit()
    assert created.id is not None
    assert created.display_name == "Первый"

    again = expenses_service.ensure_user(session, 42, username="second")
    session.commit()
    assert again.id == created.id
    assert again.username == "second"
    # full_name не затирается, если не передан
    assert again.full_name == "Первый"
    assert len(expenses_service.list_users(session)) == 1


def test_get_user_helpers(session: Session, users) -> None:
    first, second = users
    assert expenses_service.get_user(session, first.id).telegram_id == first.telegram_id
    assert expenses_service.get_user_by_telegram_id(session, second.telegram_id).id == second.id
    assert expenses_service.get_user(session, None) is None
    assert expenses_service.get_user_by_telegram_id(session, 999_999) is None


def test_normalize_amount_formats() -> None:
    assert expenses_service.normalize_amount("1 234,56") == 1234.56
    assert expenses_service.normalize_amount("1234,567") == 1234.57
    # Банковское округление (round(Decimal, 2)): половина идёт к чётному.
    assert expenses_service.normalize_amount("1234.565") == 1234.56
    assert expenses_service.normalize_amount(Decimal("10.10")) == 10.1
    assert expenses_service.normalize_amount(7) == 7.0
    with pytest.raises(ValueError):
        expenses_service.normalize_amount("не число")


def test_add_expense_fills_defaults(session: Session, user, categories) -> None:
    expense = expenses_service.add_expense(
        session,
        user=user,
        category=categories["Продукты"],
        amount="199,90",
        comment="  хлеб  ",
    )
    session.commit()
    assert expense.amount == 199.9
    assert expense.comment == "хлеб"
    assert expense.currency == "BYN"
    assert expense.spent_at <= local_now()


def test_add_expense_accepts_date_string_and_currency(
    session: Session, user, categories
) -> None:
    expense = expenses_service.add_expense(
        session,
        user=user,
        category=categories["Транспорт"],
        amount=15,
        spent_at="31.01.2025",
        currency="usd",
    )
    session.commit()
    assert expense.spent_at == datetime(2025, 1, 31)
    assert expense.currency == "USD"


def test_add_expense_strips_empty_comment(session: Session, user, categories) -> None:
    expense = expenses_service.add_expense(
        session, user=user, category=categories["Кафе"], amount=10.0, comment="   "
    )
    assert expense.comment is None


def test_delete_and_load_expense(session: Session, add_expense, user, categories) -> None:
    expense = add_expense(user, categories["Продукты"], 100.0, datetime(2024, 3, 10, 12, 0))
    loaded = expenses_service.load_expense(session, expense.id)
    assert loaded is not None
    assert loaded.category.name == "Продукты"
    assert loaded.user.id == user.id
    assert expenses_service.get_expense(session, expense.id).id == expense.id

    expenses_service.delete_expense(session, loaded)
    session.commit()
    assert expenses_service.get_expense(session, expense.id) is None
    assert expenses_service.load_expense(session, expense.id) is None


def test_expense_repr_and_relationships(session: Session, add_expense, user, categories) -> None:
    expense = add_expense(user, categories["Продукты"], 10.0)
    assert "Expense" in repr(expense)
    assert "User" in repr(user)
    assert "Category" in repr(categories["Продукты"])
    assert expense in user.expenses


def test_add_metro_expense_uses_transport_category(session: Session, user, categories) -> None:
    expense, category = expenses_service.add_metro_expense(session, user=user)
    session.commit()

    assert expenses_service.METRO_AMOUNT == 1.15
    assert category.name == "Транспорт"
    assert expense.category_id == categories["Транспорт"].id
    assert expense.amount == 1.15
    assert expense.comment == "Метро"
    assert expense.currency == "BYN"


def test_add_metro_expense_creates_transport_category(session: Session, user, categories) -> None:
    session.delete(categories["Транспорт"])
    session.flush()

    expense, category = expenses_service.add_metro_expense(session, user=user)
    session.commit()

    assert category.name == "Транспорт"
    assert "метро" in category.keyword_list
    assert expense.amount == 1.15
    assert expense.spent_at <= local_now()

