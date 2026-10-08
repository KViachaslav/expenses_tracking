"""Агрегация данных для графиков, дашборда и отчётов."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Category, Expense, User
from app.schemas import (
    CategoryTotal,
    DailyTotal,
    ExpenseOut,
    MonthlyTotal,
    PeriodComparison,
    SummaryOut,
    UserTotal,
)
from app.schemas import UserOut
from app.timeutils import (
    date_series,
    days_bounds,
    day_bounds,
    month_bounds,
    month_key,
    parse_month,
    period_days,
    previous_month_bounds,
    shift_month,
    to_date,
    today,
)

_ONE_DAY = timedelta(days=1)


# --------------------------------------------------------------------------- #
# Базовые выборки
# --------------------------------------------------------------------------- #
def build_query(
    *,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    category_ids: Sequence[int] | None = None,
    user_ids: Sequence[int] | None = None,
    search: str | None = None,
) -> Select[tuple[Expense]]:
    """SELECT по тратам с фильтрами [start, end), категории, пользователи, поиск."""
    query = select(Expense).options(joinedload(Expense.category), joinedload(Expense.user))

    conditions = _filters(
        start=start, end=end, category_ids=category_ids, user_ids=user_ids, search=search
    )
    if conditions:
        query = query.where(*conditions)
    return query


def fetch_expenses(
    session: Session,
    *,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    category_ids: Sequence[int] | None = None,
    user_ids: Sequence[int] | None = None,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Expense]:
    """Список трат (новые сверху)."""
    query = build_query(
        start=start, end=end, category_ids=category_ids, user_ids=user_ids, search=search
    ).order_by(Expense.spent_at.desc(), Expense.id.desc())
    if offset:
        query = query.offset(offset)
    if limit:
        query = query.limit(limit)
    return list(session.scalars(query).unique())


def as_datetime(value: datetime | date | str | None) -> datetime | None:
    """Приводит границу периода к naive datetime (для date — 00:00)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    parsed = to_date(value)
    if parsed is None:
        return None
    return datetime(parsed.year, parsed.month, parsed.day)


def inclusive_end(value: date | datetime | str | None) -> datetime | None:
    """«По дату включительно» -> исключающая граница (00:00 следующего дня)."""
    start = as_datetime(value)
    return start + _ONE_DAY if start else None


def _filters(
    *,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    category_ids: Sequence[int] | None = None,
    user_ids: Sequence[int] | None = None,
    search: str | None = None,
) -> list[Any]:
    """Список условий SQL по периоду/категориям/пользователям/поиску."""
    conditions: list[Any] = []
    start_dt = as_datetime(start)
    end_dt = as_datetime(end)
    if start_dt is not None:
        conditions.append(Expense.spent_at >= start_dt)
    if end_dt is not None:
        conditions.append(Expense.spent_at < end_dt)
    if category_ids:
        conditions.append(Expense.category_id.in_(list(category_ids)))
    if user_ids:
        conditions.append(Expense.user_id.in_(list(user_ids)))
    if search and search.strip():
        needle = f"%{search.strip().lower()}%"
        conditions.append(func.lower(func.coalesce(Expense.comment, "")).like(needle))
    return conditions


def total_amount(
    session: Session,
    *,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    category_ids: Sequence[int] | None = None,
    user_ids: Sequence[int] | None = None,
    search: str | None = None,
) -> float:
    """Сумма трат по фильтрам."""
    query = select(func.coalesce(func.sum(Expense.amount), 0.0))
    conditions = _filters(
        start=start, end=end, category_ids=category_ids, user_ids=user_ids, search=search
    )
    if conditions:
        query = query.where(*conditions)
    return float(session.scalar(query) or 0.0)



def summary(
    session: Session,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    *,
    category_ids: Sequence[int] | None = None,
    user_ids: Sequence[int] | None = None,
) -> SummaryOut:
    """Итог по периоду: сумма, число трат, средний расход в день."""
    start_dt = as_datetime(start) or datetime(1970, 1, 1)
    end_dt = as_datetime(end) or (start_dt + _ONE_DAY)
    start_date = start_dt.date()
    end_date = (end_dt - _ONE_DAY).date()

    query = select(
        func.coalesce(func.sum(Expense.amount), 0.0),
        func.count(Expense.id),
    )
    conditions = _filters(
        start=start_dt, end=end_dt, category_ids=category_ids, user_ids=user_ids
    )
    if conditions:
        query = query.where(*conditions)

    total, count = session.execute(query).one()
    days = period_days(start_dt, end_dt)
    total_value = float(total or 0.0)
    return SummaryOut(
        start=start_date,
        end=end_date,
        total=round(total_value, 2),
        count=int(count or 0),
        avg_per_day=round(total_value / days, 2) if days else 0.0,
        days=days,
    )


# --------------------------------------------------------------------------- #
# Ряды для графиков
# --------------------------------------------------------------------------- #
def daily_totals(
    session: Session,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    *,
    category_ids: Sequence[int] | None = None,
    user_ids: Sequence[int] | None = None,
) -> list[DailyTotal]:
    """Суммы по дням. Дни без трат заполняются нулями (для линейного графика)."""
    start_dt = as_datetime(start)
    end_dt = as_datetime(end)
    day_expr = func.date(Expense.spent_at).label("day")
    query = select(
        day_expr,
        func.coalesce(func.sum(Expense.amount), 0.0),
        func.count(Expense.id),
    ).group_by(day_expr)
    conditions = _filters(
        start=start_dt, end=end_dt, category_ids=category_ids, user_ids=user_ids
    )
    if conditions:
        query = query.where(*conditions)

    found: dict[str, tuple[float, int]] = {}
    for row in session.execute(query):
        found[str(row[0])] = (float(row[1] or 0.0), int(row[2] or 0))

    if start_dt and end_dt:
        days = date_series(start_dt.date(), (end_dt - _ONE_DAY).date())
    else:
        days = sorted(date.fromisoformat(key) for key in found)

    return [
        DailyTotal(
            day=day,
            total=round(found.get(day.isoformat(), (0.0, 0))[0], 2),
            count=found.get(day.isoformat(), (0.0, 0))[1],
        )
        for day in days
    ]


def monthly_totals(
    session: Session, months: int = 6, month: str | date | datetime | None = None
) -> list[MonthlyTotal]:
    """Суммы по месяцам (для сравнения динамики).

    Диапазон запроса — от начала первого месяца до конца последнего
    (`month`), иначе в выборку попал бы только первый месяц.
    """
    count = max(months, 1)
    last = month_key(month)
    first = shift_month(last, -(count - 1))
    start, _ = month_bounds(first)
    _, end = month_bounds(last)
    month_expr = func.strftime("%Y-%m", Expense.spent_at).label("month")
    query = (
        select(month_expr, func.coalesce(func.sum(Expense.amount), 0.0), func.count(Expense.id))
        .where(Expense.spent_at >= start, Expense.spent_at < end)
        .group_by(month_expr)
    )
    found: dict[str, tuple[float, int]] = {}
    for row in session.execute(query):
        found[str(row[0])] = (float(row[1] or 0.0), int(row[2] or 0))

    keys = [shift_month(first, offset) for offset in range(count)]
    return [
        MonthlyTotal(
            month=key,
            total=round(found.get(key, (0.0, 0))[0], 2),
            count=found.get(key, (0.0, 0))[1],
        )
        for key in keys
    ]


def category_totals(
    session: Session,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    *,
    user_ids: Sequence[int] | None = None,
    include_zero: bool = False,
) -> list[CategoryTotal]:
    """Доли категорий за период (по убыванию суммы)."""
    conditions = _filters(start=start, end=end, user_ids=user_ids)
    join_on = and_(Expense.category_id == Category.id, *conditions)
    query = (
        select(
            Category.id,
            Category.name,
            Category.emoji,
            func.coalesce(func.sum(Expense.amount), 0.0),
            func.count(Expense.id),
        )
        .select_from(Category)
        .outerjoin(Expense, join_on)
        .group_by(Category.id, Category.name, Category.emoji)
        .order_by(func.coalesce(func.sum(Expense.amount), 0.0).desc(), Category.name)
    )
    rows = session.execute(query).all()
    grand_total = sum(float(row[3] or 0.0) for row in rows)
    result: list[CategoryTotal] = []
    for category_id, name, emoji, total, count in rows:
        value = float(total or 0.0)
        if value == 0 and not include_zero:
            continue
        result.append(
            CategoryTotal(
                category_id=int(category_id),
                name=str(name),
                emoji=emoji,
                total=round(value, 2),
                count=int(count or 0),
                share=round(value / grand_total * 100, 1) if grand_total else 0.0,
            )
        )
    return result


def top_categories(
    session: Session,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
    *,
    limit: int = 5,
    user_ids: Sequence[int] | None = None,
) -> list[CategoryTotal]:
    """Топ-N категорий за период."""
    return category_totals(session, start, end, user_ids=user_ids)[: max(limit, 1)]


# --------------------------------------------------------------------------- #
# Пользователи и последние траты
# --------------------------------------------------------------------------- #
def user_totals(
    session: Session,
    start: datetime | date | str | None = None,
    end: datetime | date | str | None = None,
) -> list[UserTotal]:
    """Кто сколько потратил за период (по убыванию суммы)."""
    conditions = _filters(start=start, end=end)
    join_on = and_(Expense.user_id == User.id, *conditions)
    query = (
        select(User, func.coalesce(func.sum(Expense.amount), 0.0), func.count(Expense.id))
        .select_from(User)
        .outerjoin(Expense, join_on)
        .group_by(User.id)
        .order_by(func.coalesce(func.sum(Expense.amount), 0.0).desc(), User.id)
    )
    rows = session.execute(query).all()
    grand_total = sum(float(row[1] or 0.0) for row in rows)

    result: list[UserTotal] = []
    for user, total, count in rows:
        item = UserTotal.model_validate(user)
        item.total = round(float(total or 0.0), 2)
        item.count = int(count or 0)
        item.share = round(item.total / grand_total * 100, 1) if grand_total else 0.0
        result.append(item)
    return result


def recent_expenses(session: Session, limit: int = 10) -> list[Expense]:
    """Последние траты (для дашборда)."""
    return fetch_expenses(session, limit=max(limit, 1))


def compare_periods(
    session: Session,
    start: datetime | date | str | None,
    end: datetime | date | str | None,
) -> PeriodComparison:
    """Сравнение периода с предыдущим отрезком такой же длины."""
    start_dt = as_datetime(start) or datetime(1970, 1, 1)
    end_dt = as_datetime(end) or (start_dt + _ONE_DAY)
    length = end_dt - start_dt
    current = summary(session, start_dt, end_dt).total
    previous = summary(session, start_dt - length, start_dt).total
    delta = round(current - previous, 2)
    percent = round(delta / previous * 100, 1) if previous else None
    return PeriodComparison(
        current_total=current,
        previous_total=previous,
        delta=delta,
        delta_percent=percent,
    )


def available_months(session: Session) -> list[str]:
    """Список месяцев, за которые есть траты (по убыванию)."""
    month_expr = func.strftime("%Y-%m", Expense.spent_at)
    rows = session.scalars(select(month_expr).distinct().order_by(month_expr.desc()))
    return [str(row) for row in rows if row]


# --------------------------------------------------------------------------- #
# Pydantic-представления
# --------------------------------------------------------------------------- #
def to_expense_out(expense: Expense) -> ExpenseOut:
    return ExpenseOut.model_validate(expense)


def expenses_out(session: Session, **kwargs: Any) -> list[ExpenseOut]:
    """Список трат в виде Pydantic-схем (для REST API)."""
    return [to_expense_out(item) for item in fetch_expenses(session, **kwargs)]


