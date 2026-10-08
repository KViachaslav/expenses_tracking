"""Операции с расходами и пользователями (используются ботом, API и веб-слоем)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models import Category, Expense, User
from app.timeutils import local_now


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #
def get_user_by_telegram_id(session: Session, telegram_id: int) -> User | None:
    return session.scalar(select(User).where(User.telegram_id == telegram_id))


def get_user(session: Session, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    return session.get(User, user_id)


def ensure_user(
    session: Session,
    telegram_id: int,
    *,
    username: str | None = None,
    full_name: str | None = None,
) -> User:
    """Регистрация/обновление члена семьи по telegram_id."""
    user = get_user_by_telegram_id(session, telegram_id)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=(username or None),
            full_name=(full_name or None),
        )
        session.add(user)
        session.flush()
        return user

    changed = False
    if username and user.username != username:
        user.username = username
        changed = True
    if full_name and user.full_name != full_name:
        user.full_name = full_name
        changed = True
    if changed:
        session.flush()
    return user


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.id)))


# --------------------------------------------------------------------------- #
# Расходы
# --------------------------------------------------------------------------- #
def add_expense(
    session: Session,
    *,
    user: User,
    category: Category,
    amount: float | Decimal | str,
    comment: str | None = None,
    spent_at: datetime | str | None = None,
    currency: str | None = None,
) -> Expense:
    """Записывает трату в БД."""
    value = normalize_amount(amount)
    if value <= 0:
        raise ValueError("Сумма должна быть больше нуля")

    expense = Expense(
        user_id=user.id,
        category_id=category.id,
        amount=value,
        currency=(currency or settings.default_currency).upper(),
        comment=(comment or "").strip() or None,
        spent_at=_as_datetime(spent_at) or local_now(),
    )
    session.add(expense)
    session.flush()
    return expense


def delete_expense(session: Session, expense: Expense) -> None:
    session.delete(expense)
    session.flush()


def get_expense(session: Session, expense_id: int) -> Expense | None:
    return session.get(Expense, expense_id)


def load_expense(session: Session, expense_id: int) -> Expense | None:
    """Трата вместе со связанными категорией и пользователем."""
    return session.scalar(
        select(Expense)
        .options(joinedload(Expense.category), joinedload(Expense.user))
        .where(Expense.id == expense_id)
    )


# --------------------------------------------------------------------------- #
# Утилиты
# --------------------------------------------------------------------------- #
def normalize_amount(value: float | Decimal | str) -> float:
    """'1 234,56' | '1234.56' | Decimal -> float (округление до 2 знаков)."""
    if isinstance(value, Decimal):
        return float(round(value, 2))
    if isinstance(value, (int, float)):
        return float(round(Decimal(str(value)), 2))
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(round(Decimal(text), 2))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Некорректная сумма: {value!r}") from exc


def _as_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    from app.timeutils import to_datetime

    return to_datetime(value)
