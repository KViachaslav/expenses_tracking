"""JSON API (`/api/*`): расходы, категории, бюджеты, статистика.

Используется внешними клиентами и для отладки; веб-страницы ходят напрямую
в сервисы. Документация — `/api/docs`.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_session
from app.schemas import (
    BudgetCreate,
    BudgetProgress,
    CategoryCreate,
    CategoryOut,
    CategoryTotal,
    CategoryUpdate,
    DailyTotal,
    ExpenseCreate,
    ExpenseOut,
    MonthlyTotal,
    PeriodComparison,
    SummaryOut,
    UserTotal,
)
from app.services import budgets as budgets_service
from app.services import categories as categories_service
from app.services import expenses as expenses_service
from app.services import stats
from app.timeutils import month_bounds, month_key, to_date, today

api_router = APIRouter(prefix="/api", tags=["api"])


# --------------------------------------------------------------------------- #
# Служебное
# --------------------------------------------------------------------------- #
@api_router.get("/health", summary="Проверка живости сервиса")
def health(session: Session = Depends(get_session)) -> dict[str, object]:
    """Отдаёт статус, версию валюты по умолчанию и число категорий."""
    return {
        "status": "ok",
        "currency": settings.default_currency,
        "categories": len(categories_service.list_categories(session)),
        "month": month_key(),
    }


def _period(start: date | None, end: date | None) -> tuple[date, date]:
    """Период [start, end] включительно; по умолчанию — текущий месяц."""
    month_start = to_date(month_bounds(month_key())[0])
    first = start or month_start
    last = end or today()
    return (last, first) if last < first else (first, last)


# --------------------------------------------------------------------------- #
# Расходы
# --------------------------------------------------------------------------- #
@api_router.get("/expenses", response_model=list[ExpenseOut], summary="Список трат")
def list_expenses(
    session: Session = Depends(get_session),
    start: date | None = Query(None, description="Начало периода (включительно)"),
    end: date | None = Query(None, description="Конец периода (включительно)"),
    category_id: int | None = Query(None),
    user_id: int | None = Query(None),
    search: str | None = Query(None, description="Поиск по комментарию"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[ExpenseOut]:
    """Траты за период с фильтрами (новые сверху)."""
    return stats.expenses_out(
        session,
        start=start,
        end=stats.inclusive_end(end) if end else None,
        category_ids=[category_id] if category_id else None,
        user_ids=[user_id] if user_id else None,
        search=search,
        limit=limit,
        offset=offset,
    )


@api_router.post(
    "/expenses",
    response_model=ExpenseOut,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить трату",
)
def create_expense(payload: ExpenseCreate, session: Session = Depends(get_session)) -> ExpenseOut:
    """Создаёт трату по `category_id`/`category_name` и `user_id`/`telegram_id`."""
    category = categories_service.get_category(session, payload.category_id)
    if category is None:
        category = categories_service.find_category(session, payload.category_name)
    if category is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail=f"Категория не найдена: {payload.category_name or payload.category_id}",
        )

    user = expenses_service.get_user(session, payload.user_id)
    if user is None and payload.telegram_id is not None:
        user = expenses_service.get_user_by_telegram_id(session, payload.telegram_id)
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден — отправьте боту /start",
        )

    expense = expenses_service.add_expense(
        session,
        user=user,
        category=category,
        amount=payload.amount,
        comment=payload.comment,
        spent_at=payload.spent_at,
        currency=payload.currency,
    )
    session.commit()
    loaded = expenses_service.load_expense(session, expense.id)
    return stats.to_expense_out(loaded or expense)


@api_router.delete(
    "/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Удалить трату"
)
def remove_expense(expense_id: int, session: Session = Depends(get_session)) -> None:
    expense = expenses_service.get_expense(session, expense_id)
    if expense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Трата не найдена")
    expenses_service.delete_expense(session, expense)
    session.commit()


# --------------------------------------------------------------------------- #
# Категории
# --------------------------------------------------------------------------- #
@api_router.get("/categories", response_model=list[CategoryOut], summary="Список категорий")
def list_categories(
    session: Session = Depends(get_session),
    include_inactive: bool = Query(False, description="Показать отключённые категории"),
) -> list[CategoryOut]:
    return [
        CategoryOut.model_validate(item)
        for item in categories_service.list_categories(session, include_inactive=include_inactive)
    ]


@api_router.post(
    "/categories",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать категорию",
)
def create_category(payload: CategoryCreate, session: Session = Depends(get_session)) -> CategoryOut:
    try:
        category = categories_service.create_category(
            session, payload.name, payload.emoji, payload.synonyms
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return CategoryOut.model_validate(category)


@api_router.patch(
    "/categories/{category_id}", response_model=CategoryOut, summary="Изменить категорию"
)
def update_category(
    category_id: int, payload: CategoryUpdate, session: Session = Depends(get_session)
) -> CategoryOut:
    category = categories_service.get_category(session, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    try:
        updated = categories_service.update_category(
            session,
            category,
            name=payload.name,
            emoji=payload.emoji,
            synonyms=payload.synonyms,
            is_active=payload.is_active,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.commit()
    return CategoryOut.model_validate(updated)


@api_router.delete("/categories/{category_id}", summary="Удалить (или отключить) категорию")
def remove_category(category_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    """Возвращает `deleted=false`, если категория использована и была отключена."""
    category = categories_service.get_category(session, category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    deleted = categories_service.delete_category(session, category)
    session.commit()
    return {"deleted": deleted, "deactivated": not deleted, "id": category_id}


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #
@api_router.get("/users", response_model=list[UserTotal], summary="Траты по членам семьи")
def list_users(
    session: Session = Depends(get_session),
    start: date | None = Query(None),
    end: date | None = Query(None),
) -> list[UserTotal]:
    first, last = _period(start, end)
    return stats.user_totals(session, first, stats.inclusive_end(last))


# --------------------------------------------------------------------------- #
# Бюджеты
# --------------------------------------------------------------------------- #
@api_router.get(
    "/budgets", response_model=list[BudgetProgress], summary="Прогресс по бюджетам месяца"
)
def get_budgets(
    session: Session = Depends(get_session),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
) -> list[BudgetProgress]:
    return budgets_service.budget_progress(session, month or month_key())


@api_router.post("/budgets", summary="Сохранить лимиты на месяц")
def save_budgets(payload: list[BudgetCreate], session: Session = Depends(get_session)) -> dict[str, object]:
    """Массовое сохранение лимитов; `limit_amount = 0` удаляет лимит."""
    saved = 0
    for item in payload:
        budget = budgets_service.upsert_budget(
            session, item.month, item.limit_amount, item.category_id
        )
        if budget is not None:
            saved += 1
    session.commit()
    return {"saved": saved, "months": sorted({item.month for item in payload})}


@api_router.delete("/budgets/{budget_id}", summary="Удалить бюджет")
def remove_budget(budget_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    if not budgets_service.delete_budget(session, budget_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Бюджет не найден")
    session.commit()
    return {"deleted": True, "id": budget_id}


# --------------------------------------------------------------------------- #
# Статистика
# --------------------------------------------------------------------------- #
@api_router.get("/stats/summary", response_model=SummaryOut, summary="Итог за период")
def stats_summary(
    session: Session = Depends(get_session),
    start: date | None = Query(None),
    end: date | None = Query(None),
    category_id: int | None = Query(None),
    user_id: int | None = Query(None),
) -> SummaryOut:
    first, last = _period(start, end)
    return stats.summary(
        session,
        first,
        stats.inclusive_end(last),
        category_ids=[category_id] if category_id else None,
        user_ids=[user_id] if user_id else None,
    )


@api_router.get("/stats/compare", response_model=PeriodComparison, summary="Сравнение периодов")
def stats_compare(
    session: Session = Depends(get_session),
    start: date | None = Query(None),
    end: date | None = Query(None),
) -> PeriodComparison:
    """Сравнивает период с предыдущим отрезком такой же длины."""
    first, last = _period(start, end)
    return stats.compare_periods(session, first, stats.inclusive_end(last))


@api_router.get("/stats/daily", response_model=list[DailyTotal], summary="Суммы по дням")
def stats_daily(
    session: Session = Depends(get_session),
    start: date | None = Query(None),
    end: date | None = Query(None),
    category_id: int | None = Query(None),
    user_id: int | None = Query(None),
) -> list[DailyTotal]:
    first, last = _period(start, end)
    return stats.daily_totals(
        session,
        first,
        stats.inclusive_end(last),
        category_ids=[category_id] if category_id else None,
        user_ids=[user_id] if user_id else None,
    )


@api_router.get("/stats/monthly", response_model=list[MonthlyTotal], summary="Суммы по месяцам")
def stats_monthly(
    session: Session = Depends(get_session),
    months: int = Query(6, ge=1, le=36),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
) -> list[MonthlyTotal]:
    return stats.monthly_totals(session, months=months, month=month or month_key())


@api_router.get("/stats/categories", response_model=list[CategoryTotal], summary="Разбивка по категориям")
def stats_categories(
    session: Session = Depends(get_session),
    start: date | None = Query(None),
    end: date | None = Query(None),
    user_id: int | None = Query(None),
    include_zero: bool = Query(False),
) -> list[CategoryTotal]:
    first, last = _period(start, end)
    return stats.category_totals(
        session,
        first,
        stats.inclusive_end(last),
        user_ids=[user_id] if user_id else None,
        include_zero=include_zero,
    )


# ==== APPEND HERE ====
