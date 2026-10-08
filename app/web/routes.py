"""Веб-интерфейс: FastAPI + Jinja2 (дашборд, отчёты, категории, пользователи).

Запуск (см. `deploy/expense-web.service`):

    uvicorn app.web.routes:app --host 0.0.0.0 --port 8080

или `python run_web.py` — тогда хост и порт берутся из `WEB_HOST`/`WEB_PORT`.

Авторизации нет — сервис рассчитан на доступ только из локальной сети
(см. `README.md`, раздел про `ufw`).
"""

from __future__ import annotations

import csv
import inspect
import io
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import formatting
from app.config import settings
from app.database import get_session, init_db
from app.services import budgets as budgets_service
from app.services import categories as categories_service
from app.services import expenses as expenses_service
from app.services import stats
from app.timeutils import (
    day_bounds,
    days_bounds,
    month_bounds,
    month_days,
    month_key,
    month_label,
    parse_month,
    previous_month_bounds,
    to_date,
    today,
)
from app.web.api.routes import api_router

WEB_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Локальный Chart.js (если лежит в static/) имеет приоритет над CDN.
CHART_LOCAL = (STATIC_DIR / "chart.umd.min.js").exists()

TREND_DAYS = 30
TABLE_LIMIT = 50
DASHBOARD_EXPENSES = 10

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Создаёт таблицы и справочник категорий при старте (идемпотентно)."""
    init_db()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Семейные расходы",
    description="Веб-интерфейс семейного учёта трат (Telegram-бот + FastAPI + SQLite).",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(api_router)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    money=formatting.format_money,
    amount=formatting.format_amount,
    percent=formatting.format_percent,
    date_ru=formatting.format_date,
    datetime_ru=formatting.format_datetime,
    plural=formatting.plural_ru,
    month_label=month_label,
    month_key=month_key,
    currency=settings.default_currency,
    chart_local=CHART_LOCAL,
    app_title="Семейные расходы",
)

# Совместимость: Starlette >= 0.29 принимает request первым аргументом.
_FIRST_PARAM = next(iter(inspect.signature(templates.TemplateResponse).parameters))


def render(request: Request, name: str, **context: Any) -> HTMLResponse:
    """Рендерит Jinja2-шаблон (работает с обеими версиями Starlette)."""
    context.setdefault("request", request)
    if _FIRST_PARAM == "request":
        return templates.TemplateResponse(request, name, context)
    return templates.TemplateResponse(name, context)


# --------------------------------------------------------------------------- #
# Разбор параметров запроса
# --------------------------------------------------------------------------- #
def _int(value: str | None) -> int | None:
    """Строка -> int или None (пустые значения игнорируются)."""
    if value is None or not str(value).strip():
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _float(value: str | None) -> float | None:
    """Строка -> float, поддерживает '1 234,56' (пусто -> None)."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _day(value: str | None) -> date | None:
    """'2025-01-31' | '31.01.2025' -> date (иначе None)."""
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _text(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _month(value: str | None) -> str:
    """"YYYY-MM" из запроса; некорректное значение -> текущий месяц."""
    text = (value or "").strip()
    if not text:
        return month_key()
    try:
        return parse_month(text)
    except ValueError:
        return month_key()


def _redirect(url: str, msg: str | None = None) -> RedirectResponse:
    """Post/Redirect/Get с необязательным сообщением (?msg=)."""
    if msg:
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}msg={quote(msg)}"
    return RedirectResponse(url=url, status_code=303)


def _period(start_raw: str | None, end_raw: str | None) -> tuple[date, date]:
    """Период [start, end] включительно; по умолчанию — текущий месяц."""
    month_start = to_date(month_bounds(month_key())[0])
    start = _day(start_raw) or month_start
    end = _day(end_raw) or today()
    if end < start:
        start, end = end, start
    return start, end


def _safe_back(url: str | None, default: str) -> str:
    """Защита от open-redirect: принимаем только локальный путь."""
    text = (url or "").strip()
    if text.startswith("/") and not text.startswith("//"):
        return text
    return default


def _list_context(
    session: Session,
    *,
    start: date,
    end: date,
    category_id: int | None,
    user_id: int | None,
    search: str | None,
) -> dict[str, Any]:
    """Общий контекст страниц со фильтрами (период / категория / автор / поиск)."""
    return {
        "filters": {
            "start": start,
            "end": end,
            "category_id": category_id,
            "user_id": user_id,
            "search": search,
        },
        "categories": categories_service.list_categories(session, include_inactive=True),
        "users": expenses_service.list_users(session),
    }


def _chart_json(payload: dict[str, Any]) -> str:
    """JSON для вставки в <script> (кириллица не экранируется, '<' — да)."""
    text = json.dumps(payload, ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# --------------------------------------------------------------------------- #
# Дашборд
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse, summary="Дашборд")
def dashboard(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Главная страница: карточки, графики, бюджеты и последние траты."""
    month = month_key()
    month_start, month_end = month_bounds(month)
    today_start, today_end = day_bounds(today())

    today_summary = stats.summary(session, today_start, today_end)
    month_summary = stats.summary(session, month_start, month_end)
    comparison = stats.compare_periods(session, month_start, month_end)
    overall = budgets_service.overall_progress(session, month)

    daily = stats.daily_totals(session, *days_bounds(today(), TREND_DAYS))
    by_category = stats.category_totals(session, month_start, month_end)
    top = stats.top_categories(session, month_start, month_end, limit=5)
    months = stats.monthly_totals(session, months=6, month=month)
    progress = budgets_service.budget_progress(session, month)

    if overall is None:
        budget_state = "none"
    elif overall.over:
        budget_state = "bad"
    elif overall.percent >= 80:
        budget_state = "warn"
    else:
        budget_state = "good"

    chart = {
        "trend": {
            "labels": [item.day.strftime("%d.%m") for item in daily],
            "values": [item.total for item in daily],
        },
        "categories": {
            "labels": [item.title for item in by_category],
            "values": [item.total for item in by_category],
        },
        "top": {
            "labels": [item.title for item in top],
            "values": [item.total for item in top],
        },
        "months": {
            "labels": [month_label(item.month) for item in months],
            "values": [item.total for item in months],
        },
    }

    return render(
        request,
        "dashboard.html",
        active="dashboard",
        month=month,
        month_title=month_label(month),
        days_left=max(month_days(month) - today().day, 0),
        today_summary=today_summary,
        month_summary=month_summary,
        comparison=comparison,
        overall=overall,
        budget_state=budget_state,
        progress=progress,
        overall_limit=overall.limit_amount if overall else None,
        limits={
            item.category_id: item.limit_amount
            for item in progress
            if item.category_id is not None
        },
        categories=categories_service.list_categories(session),
        recent=stats.recent_expenses(session, DASHBOARD_EXPENSES),
        chart_json=_chart_json(chart),
    )


# --------------------------------------------------------------------------- #
# Траты: список / добавление / удаление
# --------------------------------------------------------------------------- #
@app.get("/expenses", response_class=HTMLResponse, summary="Список трат")
def expenses_page(
    request: Request,
    session: Session = Depends(get_session),
    start: str | None = Query(None),
    end: str | None = Query(None),
    category: str | None = Query(None),
    user: str | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """Таблица трат с фильтрами, пагинацией и формой ручного добавления."""
    start_date, end_date = _period(start, end)
    category_id = _int(category)
    user_id = _int(user)
    needle = _text(search)
    end_dt = stats.inclusive_end(end_date)

    rows = stats.fetch_expenses(
        session,
        start=start_date,
        end=end_dt,
        category_ids=[category_id] if category_id else None,
        user_ids=[user_id] if user_id else None,
        search=needle,
        limit=TABLE_LIMIT + 1,
        offset=(page - 1) * TABLE_LIMIT,
    )

    return render(
        request,
        "expenses.html",
        active="expenses",
        rows=rows[:TABLE_LIMIT],
        page=page,
        has_next=len(rows) > TABLE_LIMIT,
        table_limit=TABLE_LIMIT,
        total=stats.total_amount(
            session,
            start=start_date,
            end=end_dt,
            category_ids=[category_id] if category_id else None,
            user_ids=[user_id] if user_id else None,
            search=needle,
        ),
        default_date=today(),
        **_list_context(
            session,
            start=start_date,
            end=end_date,
            category_id=category_id,
            user_id=user_id,
            search=needle,
        ),
    )


@app.post("/expenses", summary="Добавить трату из веб-формы")
async def expense_create(
    request: Request, session: Session = Depends(get_session)
) -> RedirectResponse:
    """Ручной ввод траты (обычно удобнее через бота)."""
    form = await request.form()
    back = _safe_back(str(form.get("back") or ""), "/expenses")
    amount = _float(str(form.get("amount") or ""))
    category = categories_service.get_category(session, _int(str(form.get("category_id") or "")))
    user = expenses_service.get_user(session, _int(str(form.get("user_id") or "")))

    if amount is None or amount <= 0 or category is None or user is None:
        return _redirect(back, "Нужны сумма, категория и автор траты")

    expenses_service.add_expense(
        session,
        user=user,
        category=category,
        amount=amount,
        comment=str(form.get("comment") or "").strip() or None,
        spent_at=_day(str(form.get("spent_at") or "")) or today(),
    )
    session.commit()
    return _redirect(back, "Трата добавлена")


@app.post("/expenses/{expense_id}/delete", summary="Удалить трату")
async def expense_delete(
    expense_id: int, request: Request, session: Session = Depends(get_session)
) -> RedirectResponse:
    form = await request.form()
    back = _safe_back(str(form.get("back") or ""), "/expenses")
    expense = expenses_service.get_expense(session, expense_id)
    if expense is None:
        return _redirect(back, "Трата не найдена")
    expenses_service.delete_expense(session, expense)
    session.commit()
    return _redirect(back, "Трата удалена")


# --------------------------------------------------------------------------- #
# Отчёты
# --------------------------------------------------------------------------- #
@app.get("/reports", response_class=HTMLResponse, summary="Отчёты")
def reports_page(
    request: Request,
    session: Session = Depends(get_session),
    start: str | None = Query(None),
    end: str | None = Query(None),
    category: str | None = Query(None),
    user: str | None = Query(None),
    months: int = Query(6, ge=1, le=36),
) -> HTMLResponse:
    """Итоги за период: суммы, категории, авторы, динамика по месяцам."""
    start_date, end_date = _period(start, end)
    category_id = _int(category)
    user_id = _int(user)
    end_dt = stats.inclusive_end(end_date)
    category_ids = [category_id] if category_id else None
    user_ids = [user_id] if user_id else None

    return render(
        request,
        "reports.html",
        active="reports",
        summary=stats.summary(
            session, start_date, end_dt, category_ids=category_ids, user_ids=user_ids
        ),
        comparison=stats.compare_periods(session, start_date, end_dt),
        by_category=stats.category_totals(session, start_date, end_dt, user_ids=user_ids),
        by_user=stats.user_totals(session, start_date, end_dt),
        daily=stats.daily_totals(
            session, start_date, end_dt, category_ids=category_ids, user_ids=user_ids
        ),
        by_month=stats.monthly_totals(session, months=months, month=month_key(end_date)),
        available=stats.available_months(session),
        months=months,
        **_list_context(
            session,
            start=start_date,
            end=end_date,
            category_id=category_id,
            user_id=user_id,
            search=None,
        ),
    )


@app.get("/reports/export.csv", summary="Экспорт трат в CSV")
def export_csv(
    session: Session = Depends(get_session),
    start: str | None = Query(None),
    end: str | None = Query(None),
    category: str | None = Query(None),
    user: str | None = Query(None),
    search: str | None = Query(None),
) -> StreamingResponse:
    """CSV с разделителем ';' и BOM — корректно открывается в Excel."""
    start_date, end_date = _period(start, end)
    category_id = _int(category)
    user_id = _int(user)

    rows = stats.fetch_expenses(
        session,
        start=start_date,
        end=stats.inclusive_end(end_date),
        category_ids=[category_id] if category_id else None,
        user_ids=[user_id] if user_id else None,
        search=_text(search),
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Дата", "Сумма", "Валюта", "Категория", "Кто", "Комментарий"])
    for item in rows:
        writer.writerow(
            [
                item.spent_at.strftime("%d.%m.%Y %H:%M"),
                f"{float(item.amount):.2f}".replace(".", ","),
                item.currency,
                item.category.name if item.category else "",
                item.user.display_name if item.user else "",
                (item.comment or "").replace("\n", " "),
            ]
        )
    total = sum(float(item.amount) for item in rows)
    writer.writerow([])
    writer.writerow(["Итого", f"{total:.2f}".replace(".", ","), "", "", "", ""])

    body = "\ufeff" + buffer.getvalue()
    filename = f"expenses_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv"
    return StreamingResponse(
        iter([body.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# Категории
# --------------------------------------------------------------------------- #
@app.get("/categories", response_class=HTMLResponse, summary="Категории")
def categories_page(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    """Справочник: синонимы для быстрого ввода, использование, вкл/выкл."""
    usage = categories_service.category_usage(session)
    rows = [
        {
            "category": category,
            "total": usage.get(category.id, (0.0, 0))[0],
            "count": usage.get(category.id, (0.0, 0))[1],
        }
        for category in categories_service.list_categories(session, include_inactive=True)
    ]
    return render(
        request,
        "categories.html",
        active="categories",
        rows=rows,
        month=month_key(),
    )


@app.post("/categories", summary="Создать категорию")
async def category_create(
    request: Request, session: Session = Depends(get_session)
) -> RedirectResponse:
    form = await request.form()
    back = _safe_back(str(form.get("back") or ""), "/categories")
    try:
        categories_service.create_category(
            session,
            str(form.get("name") or ""),
            str(form.get("emoji") or "").strip() or None,
            str(form.get("synonyms") or ""),
        )
    except ValueError as exc:
        return _redirect(back, str(exc))
    session.commit()
    return _redirect(back, "Категория добавлена")


@app.post("/categories/{category_id}", summary="Изменить категорию")
async def category_update(
    category_id: int, request: Request, session: Session = Depends(get_session)
) -> RedirectResponse:
    form = await request.form()
    back = _safe_back(str(form.get("back") or ""), "/categories")
    category = categories_service.get_category(session, category_id)
    if category is None:
        return _redirect(back, "Категория не найдена")
    try:
        categories_service.update_category(
            session,
            category,
            name=str(form.get("name") or "") or None,
            emoji=str(form.get("emoji") or ""),
            synonyms=str(form.get("synonyms") or ""),
            is_active=form.get("is_active") is not None,
        )
    except ValueError as exc:
        return _redirect(back, str(exc))
    session.commit()
    return _redirect(back, "Категория сохранена")


@app.post("/categories/{category_id}/delete", summary="Удалить или отключить категорию")
async def category_delete(
    category_id: int, request: Request, session: Session = Depends(get_session)
) -> RedirectResponse:
    form = await request.form()
    back = _safe_back(str(form.get("back") or ""), "/categories")
    category = categories_service.get_category(session, category_id)
    if category is None:
        return _redirect(back, "Категория не найдена")
    deleted = categories_service.delete_category(session, category)
    session.commit()
    message = "Категория удалена" if deleted else "По категории есть траты — она отключена"
    return _redirect(back, message)


# --------------------------------------------------------------------------- #
# Семья (траты по пользователям)
# --------------------------------------------------------------------------- #
@app.get("/users", response_class=HTMLResponse, summary="Семья")
def users_page(
    request: Request,
    session: Session = Depends(get_session),
    month: str | None = Query(None),
) -> HTMLResponse:
    """Кто сколько потратил за выбранный месяц и как это изменилось."""
    key = _month(month)
    start, end = month_bounds(key)
    previous_start, previous_end = previous_month_bounds(key)
    rows = [item for item in stats.user_totals(session, start, end) if item.count]
    previous = {
        item.id: item.total
        for item in stats.user_totals(session, previous_start, previous_end)
        if item.count
    }

    return render(
        request,
        "users.html",
        active="users",
        month=key,
        month_title=month_label(key),
        previous_month=month_key(previous_start),
        rows=rows,
        previous=previous,
        summary=stats.summary(session, start, end),
        available=stats.available_months(session),
        chart_json=_chart_json(
            {
                "labels": [item.display_name for item in rows],
                "values": [item.total for item in rows],
            }
        ),
    )


# --------------------------------------------------------------------------- #
# Бюджеты (форма на дашборде)
# --------------------------------------------------------------------------- #
@app.post("/budgets", summary="Сохранить лимиты на месяц")
async def budgets_save(
    request: Request, session: Session = Depends(get_session)
) -> RedirectResponse:
    """Принимает `limit_overall` и `limit_<category_id>`; 0/пусто — убрать лимит."""
    form = await request.form()
    back = _safe_back(str(form.get("back") or ""), "/")
    month = _month(str(form.get("month") or ""))

    values: dict[int | None, float] = {}
    for key, value in form.items():
        if not key.startswith("limit_"):
            continue
        amount = _float(str(value)) or 0.0
        if key == "limit_overall":
            values[None] = amount
            continue
        category_id = _int(key[len("limit_") :])
        if category_id is not None:
            values[category_id] = amount

    saved = budgets_service.save_budgets(session, month, values)
    session.commit()
    return _redirect(back, f"Бюджеты на {month_label(month)}: сохранено записей — {saved}")


# ==== APPEND HERE ====
