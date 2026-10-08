"""Смоук-проверка веб-слоя (FastAPI + Jinja2) без реальных Telegram-токенов.

Запуск:

    python devcheck_web.py

Скрипт подменяет БД на временный SQLite-файл, наполняет её данными и проверяет
рендер всех страниц, Post/Redirect/Get форм, CSV-экспорт и JSON API.
Результат печатается в stdout (перенаправляйте в файл, если консоль капризничает).
"""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

# Консоль Windows часто в cp1251 и падает на эмодзи — печатаем в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_TMP_DIR = tempfile.mkdtemp(prefix="zatrats_web_")
# app.config читает DB_PATH (а не DATABASE_URL), поэтому подменяем именно его.
os.environ["DB_PATH"] = os.path.join(_TMP_DIR, "devcheck.db")
os.environ["SEED_DEFAULT_CATEGORIES"] = "1"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "000000:devcheck")

from datetime import timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal, init_db  # noqa: E402
from app.services import categories as categories_service  # noqa: E402
from app.services import expenses as expenses_service  # noqa: E402
from app.timeutils import local_now  # noqa: E402
from app.web.routes import app  # noqa: E402

results: list[str] = []


def check(name: str, condition: bool, extra: str = "") -> None:
    mark = "OK  " if condition else "FAIL"
    results.append(f"[{mark}] {name}{(' :: ' + extra) if extra else ''}")


def seed() -> None:
    """Наполняет временную БД двумя пользователями и тремя тратами."""
    from sqlalchemy import select

    from app.models import User

    init_db()
    with SessionLocal() as session:
        cats = categories_service.list_categories(session, include_inactive=True)
        now = local_now()
        for index in range(2):
            session.add(
                User(
                    telegram_id=100 + index,
                    username=f"user{index}",
                    full_name=f"Тестовый {index}",
                    created_at=now,
                )
            )
        session.commit()
        users = list(session.scalars(select(User).order_by(User.id)))
        plan = [
            (cats[0], users[0], 500.0, now - timedelta(days=1), "продукты"),
            (cats[1], users[1], 120.5, now - timedelta(days=2), "такси"),
            (cats[0], users[1], 45.25, now, None),
        ]
        for category, user, amount, spent_at, comment in plan:
            expenses_service.add_expense(
                session,
                user=user,
                category=category,
                amount=amount,
                comment=comment,
                spent_at=spent_at,
            )
        session.commit()


def main() -> None:
    seed()
    with TestClient(app) as client:
        for url in ("/", "/expenses", "/reports", "/categories", "/users", "/expenses?page=2"):
            response = client.get(url)
            check(f"GET {url} -> 200", response.status_code == 200, str(response.status_code))
            check(f"GET {url}: полный HTML", response.text.startswith("<!doctype html>"))

        dashboard = client.get("/").text
        check("дашборд: данные графиков вклеены", '"trend"' in dashboard and '"months"' in dashboard)
        check("дашборд: блок последних трат", "Последние траты" in dashboard)
        check("дашборд: валюта и формат", "BYN" in dashboard and "665,75" in dashboard)
        check("дашборд: форма бюджетов", 'name="limit_overall"' in dashboard)

        reports = client.get("/reports").text
        check("отчёты: категории и семья", "По категориям" in reports and "По членам семьи" in reports)
        check("отчёты: динамика по месяцам", "Динамика по месяцам" in reports)
        check("отчёты: строки по дням", "По дням периода" in reports)
        check("отчёты: ссылка на CSV", "/reports/export.csv" in reports)

        csv_response = client.get("/reports/export.csv")
        check(
            "CSV: 200 + BOM + разделитель ';'",
            csv_response.status_code == 200
            and csv_response.text.startswith("\ufeff")
            and ";" in csv_response.text,
            csv_response.headers.get("content-disposition", ""),
        )
        check("CSV: данные и итог", "Тестовый" in csv_response.text and "Итого" in csv_response.text)

        created = client.post(
            "/expenses",
            data={
                "amount": "99,90",
                "category_id": "1",
                "user_id": "1",
                "spent_at": local_now().strftime("%Y-%m-%d"),
                "comment": "проверка формы",
                "back": "/expenses",
            },
            follow_redirects=False,
        )
        check("POST /expenses -> 303", created.status_code == 303, str(created.status_code))
        check("POST /expenses: запись видна", "проверка формы" in client.get("/expenses").text)

        saved = client.post(
            "/budgets",
            data={
                "month": local_now().strftime("%Y-%m"),
                "limit_overall": "1000",
                "limit_1": "500",
                "back": "/",
            },
            follow_redirects=False,
        )
        check("POST /budgets -> 303", saved.status_code == 303, str(saved.status_code))
        check(
            "POST /budgets: лимит виден на дашборде",
            "1\u00a0000,00" in client.get("/").text,
        )

        new_category = client.post(
            "/categories",
            data={"name": "Проверка", "emoji": "🧪", "synonyms": "чек, тест", "back": "/categories"},
            follow_redirects=False,
        )
        check("POST /categories -> 303", new_category.status_code == 303, str(new_category.status_code))
        page = client.get("/categories").text
        check("POST /categories: категория создана", "Проверка" in page and "🧪" in page)

        updated = client.post(
            "/categories/1",
            data={
                "name": "Продукты+",
                "emoji": "🛒",
                "synonyms": "продукты, еда",
                "is_active": "1",
                "back": "/categories",
            },
            follow_redirects=False,
        )
        check("POST /categories/1 -> 303", updated.status_code == 303, str(updated.status_code))
        check("POST /categories/1: имя обновлено", "Продукты+" in client.get("/categories").text)

        deleted = client.post("/categories/1/delete", data={"back": "/categories"}, follow_redirects=False)
        check(
            "POST /categories/1/delete -> 303 (есть траты -> отключение)",
            deleted.status_code == 303,
            str(deleted.status_code),
        )
        check(
            "отключённая категория помечена как неактивная",
            'id="act1"' in client.get("/categories").text,
        )

        expenses_page = client.get("/expenses").text
        check("траты: фильтры и форма добавления", "Фильтры" in expenses_page and "Добавить" in expenses_page)

        users_page = client.get("/users").text
        check("семья: таблица по участникам", "Кто сколько потратил" in users_page and "Тестовый" in users_page)

        health = client.get("/api/health")
        check("GET /api/health -> 200", health.status_code == 200, health.text[:200])
        api_expenses = client.get("/api/expenses")
        check("GET /api/expenses -> 200", api_expenses.status_code == 200, api_expenses.text[:120])
        api_summary = client.get("/api/stats/summary")
        check("GET /api/stats/summary -> 200", api_summary.status_code == 200, api_summary.text[:120])
        api_categories = client.get("/api/categories")
        check("GET /api/categories -> 200", api_categories.status_code == 200, api_categories.text[:120])
        api_users = client.get("/api/users")
        check("GET /api/users -> 200", api_users.status_code == 200, api_users.text[:120])
        docs = client.get("/api/docs")
        check("GET /api/docs -> 200", docs.status_code == 200, str(docs.status_code))

        missing = client.get("/expenses/999999/delete")
        check("GET на POST-роут -> 405", missing.status_code == 405, str(missing.status_code))

    failed = [line for line in results if line.startswith("[FAIL]")]
    results.append("")
    results.append(f"Итого проверок: {len(results) - 1}, провалено: {len(failed)}")
    print("\n".join(results))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # pragma: no cover - диагностика для ручного прогона
        print("\n".join(results))
        print("НЕОЖИДАННАЯ ОШИБКА:")
        traceback.print_exc()
        raise

