"""Бюджеты на месяц: лимиты (общие и по категориям) и прогресс их исполнения."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Budget, Category
from app.schemas import BudgetProgress
from app.services import stats
from app.timeutils import month_bounds, month_key


def list_budgets(session: Session, month: str | date | datetime | None = None) -> list[Budget]:
    """Все бюджеты на месяц (общий + по категориям)."""
    key = month_key(month)
    return list(
        session.scalars(
            select(Budget)
            .options(joinedload(Budget.category))
            .where(Budget.month == key)
            .order_by(Budget.category_id.is_(None).desc(), Budget.id)
        )
    )


def get_budget(
    session: Session,
    month: str | date | datetime | None,
    category_id: int | None = None,
) -> Budget | None:
    key = month_key(month)
    query = select(Budget).where(Budget.month == key)
    query = query.where(Budget.category_id.is_(None) if category_id is None else Budget.category_id == category_id)
    return session.scalar(query)


def upsert_budget(
    session: Session,
    month: str | date | datetime | None,
    limit_amount: float,
    category_id: int | None = None,
) -> Budget | None:
    """Ставит лимит на месяц. limit_amount <= 0 -> бюджет удаляется."""
    key = month_key(month)
    budget = get_budget(session, key, category_id)
    if limit_amount is None or float(limit_amount) <= 0:
        if budget is not None:
            session.delete(budget)
            session.flush()
        return None

    if budget is None:
        budget = Budget(month=key, category_id=category_id, limit_amount=float(limit_amount))
        session.add(budget)
    else:
        budget.limit_amount = float(limit_amount)
    session.flush()
    return budget


def save_budgets(
    session: Session,
    month: str | date | datetime | None,
    values: Mapping[int | None, float],
) -> int:
    """Массовое сохранение лимитов {category_id|None: сумма}. Возвращает число записей."""
    saved = 0
    for category_id, limit_amount in values.items():
        budget = upsert_budget(session, month, limit_amount, category_id)
        if budget is not None:
            saved += 1
    return saved


def delete_budget(session: Session, budget_id: int) -> bool:
    budget = session.get(Budget, budget_id)
    if budget is None:
        return False
    session.delete(budget)
    session.flush()
    return True


def budget_progress(
    session: Session,
    month: str | date | datetime | None = None,
    *,
    include_empty: bool = False,
) -> list[BudgetProgress]:
    """Прогресс по бюджетам месяца (общий бюджет — первым)."""
    key = month_key(month)
    start, end = month_bounds(key)
    by_category = {item.category_id: item for item in stats.category_totals(session, start, end)}
    month_total = stats.summary(session, start, end).total

    result: list[BudgetProgress] = []
    for budget in list_budgets(session, key):
        if budget.category_id is None:
            spent = month_total
            category = None
            name = "Всё вместе"
            emoji = "🎯"
        else:
            category = by_category.get(budget.category_id)
            spent = category.total if category else 0.0
            name = category.name if category else (budget.category.name if budget.category else "—")
            emoji = category.emoji if category else (budget.category.emoji if budget.category else None)

        limit_amount = float(budget.limit_amount or 0.0)
        remaining = round(limit_amount - spent, 2)
        result.append(
            BudgetProgress(
                budget_id=budget.id,
                month=key,
                category_id=budget.category_id,
                category_name=name,
                emoji=emoji,
                limit_amount=round(limit_amount, 2),
                spent=round(spent, 2),
                remaining=remaining,
                percent=round(spent / limit_amount * 100, 1) if limit_amount else 0.0,
                over=remaining < 0,
            )
        )
    return result


def overall_progress(
    session: Session, month: str | date | datetime | None = None
) -> BudgetProgress | None:
    """Общий бюджет месяца (если задан) — для карточки «остаток бюджета»."""
    for item in budget_progress(session, month):
        if item.category_id is None:
            return item
    return None


def remaining_for(
    session: Session, month: str | date | datetime | None = None
) -> float | None:
    """Остаток общего бюджета или None, если бюджет не задан."""
    overall = overall_progress(session, month)
    return None if overall is None else overall.remaining
