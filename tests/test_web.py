"""Тесты веб-слоя (`app.web.routes`): страницы, формы, экспорт CSV.

Проверяем через `TestClient`, то есть тем же путём, которым ходит браузер:
роуты берут сессию из `app.database`, поэтому изменения из форм видны в тестовой
сессии только после `session.expire_all()` (другое соединение к тому же файлу).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services import budgets as budgets_service
from app.services import categories as categories_service
from app.services import expenses as expenses_service
from app.services import stats
from app.timeutils import month_key, month_label, today

PAGES = ("/", "/expenses", "/reports", "/categories", "/users")
MARCH = datetime(2024, 3, 5, 13, 0)


def test_pages_render(client: TestClient) -> None:
    for path in PAGES:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers["content-type"].startswith("text/html")
        assert "Семейные расходы" in response.text
        assert "/api/docs" in response.text


def test_static_and_api_docs(client: TestClient) -> None:
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]

    docs = client.get("/api/docs")
    assert docs.status_code == 200
    assert client.get("/api/openapi.json").json()["info"]["title"] == "Семейные расходы"


def test_dashboard_shows_today_and_month(client: TestClient, today_expense) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "150,00" in response.text  # карточка «за сегодня»
    assert "свежая трата" in response.text  # блок последних трат
    assert month_label(month_key()) in response.text


def test_expenses_page_filters(client: TestClient, user, categories, add_expense) -> None:
    add_expense(user, categories["Продукты"], 150.0, None, "свежая трата")
    add_expense(user, categories["Кафе"], 40.0, MARCH, "старая покупка")

    current = client.get("/expenses")  # по умолчанию — текущий месяц
    assert current.status_code == 200
    assert "свежая трата" in current.text
    assert "старая покупка" not in current.text

    march = client.get(
        "/expenses",
        params={"start": "2024-03-01", "end": "2024-03-31", "search": "старая"},
    )
    assert march.status_code == 200
    assert "старая покупка" in march.text
    assert "свежая трата" not in march.text

    filtered = client.get(
        "/expenses",
        params={"category": str(categories["Продукты"].id), "user": str(user.id)},
    )
    assert filtered.status_code == 200
    assert "свежая трата" in filtered.text

    assert client.get("/expenses", params={"page": 2}).status_code == 200
    # Мусор в датах не ломает страницу — берётся текущий месяц.
    broken = client.get("/expenses", params={"start": "abc", "end": "31-31-2024"})
    assert broken.status_code == 200
    assert "свежая трата" in broken.text


def test_expense_create_via_form(
    client: TestClient, session: Session, user, categories
) -> None:
    response = client.post(
        "/expenses",
        data={
            "amount": "1 234,56",
            "category_id": str(categories["Кафе"].id),
            "user_id": str(user.id),
            "comment": "обед в кафе",
            "spent_at": today().strftime("%d.%m.%Y"),
            "back": "/expenses",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Трата добавлена" in response.text

    session.expire_all()
    rows = stats.fetch_expenses(session)
    assert len(rows) == 1
    expense = rows[0]
    assert expense.amount == 1234.56
    assert expense.comment == "обед в кафе"
    assert expense.spent_at.date() == today()
    assert expense.category_id == categories["Кафе"].id
    assert expense.user_id == user.id


def test_expense_form_validation_and_safe_redirect(
    client: TestClient, session: Session
) -> None:
    response = client.post(
        "/expenses",
        data={"amount": "", "back": "https://evil.example.com/login"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    # open-redirect отсекается: возвращаемся на локальный список трат
    assert response.headers["location"].startswith("/expenses?msg=")

    page = client.post("/expenses", data={"amount": "0"}, follow_redirects=True)
    assert "Нужны сумма, категория и автор траты" in page.text

    session.expire_all()
    assert stats.fetch_expenses(session) == []


def test_expense_delete_via_form(
    client: TestClient, session: Session, today_expense
) -> None:
    expense_id = today_expense.id
    response = client.post(
        f"/expenses/{expense_id}/delete",
        data={"back": "/expenses"},
        follow_redirects=True,
    )
    assert "Трата удалена" in response.text

    session.expire_all()
    assert expenses_service.get_expense(session, expense_id) is None

    missing = client.post("/expenses/999999/delete", data={}, follow_redirects=True)
    assert "Трата не найдена" in missing.text


def test_category_forms(client: TestClient, session: Session, categories) -> None:
    create = client.post(
        "/categories",
        data={
            "name": "  Дача  ",
            "emoji": "🏡",
            "synonyms": " огород , участок ",
            "back": "/categories",
        },
        follow_redirects=True,
    )
    assert create.status_code == 200
    assert "Категория добавлена" in create.text

    session.expire_all()
    dacha = categories_service.find_by_name(session, "дача")
    assert dacha is not None
    assert (dacha.name, dacha.emoji) == ("Дача", "🏡")
    assert dacha.keyword_list == ["дача", "огород", "участок"]
    dacha_id = dacha.id

    duplicate = client.post(
        "/categories", data={"name": "дача", "back": "/categories"}, follow_redirects=True
    )
    assert "уже существует" in duplicate.text
    assert len(categories_service.list_categories(session, include_inactive=True)) == 9

    updated = client.post(
        f"/categories/{dacha_id}",
        data={
            "name": "Загород",
            "emoji": "🌳",
            "synonyms": "",
            "is_active": "on",
            "back": "/categories",
        },
        follow_redirects=True,
    )
    assert "Категория сохранена" in updated.text
    session.expire_all()
    saved = categories_service.get_category(session, dacha_id)
    assert (saved.name, saved.emoji, saved.synonyms) == ("Загород", "🌳", "")
    assert saved.is_active is True

    # Чекбокс «активна» не передан -> категория отключается.
    client.post(f"/categories/{dacha_id}", data={"name": "Загород", "back": "/categories"})
    session.expire_all()
    assert categories_service.get_category(session, dacha_id).is_active is False

    deleted = client.post(
        f"/categories/{dacha_id}/delete", data={"back": "/categories"}, follow_redirects=True
    )
    assert "Категория удалена" in deleted.text
    session.expire_all()
    assert categories_service.get_category(session, dacha_id) is None

    unknown = client.post("/categories/999999", data={"name": "X"}, follow_redirects=True)
    assert "Категория не найдена" in unknown.text
    unknown_delete = client.post("/categories/999999/delete", data={}, follow_redirects=True)
    assert "Категория не найдена" in unknown_delete.text
    empty = client.post("/categories", data={"name": "   "}, follow_redirects=True)
    assert "не может быть пустым" in empty.text

def test_category_delete_used_is_deactivated(
    client: TestClient, session: Session, categories, add_expense, user
) -> None:
    products = categories["Продукты"]
    add_expense(user, products, 100.0, None, "хлеб")

    response = client.post(
        f"/categories/{products.id}/delete", data={"back": "/categories"}, follow_redirects=True
    )
    assert "По категории есть траты — она отключена" in response.text

    session.expire_all()
    assert categories_service.get_category(session, products.id).is_active is False
    assert len(categories_service.list_categories(session)) == 7


def test_budgets_form_and_dashboard_progress(
    client: TestClient, session: Session, categories, add_expense, user
) -> None:
    month = month_key()
    products = categories["Продукты"]
    add_expense(user, products, 150.0, None, "хлеб")

    response = client.post(
        "/budgets",
        data={
            "month": month,
            "limit_overall": "10 000",
            f"limit_{products.id}": "500",
            "back": "/",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "сохранено записей — 2" in response.text

    session.expire_all()
    saved = {
        item.category_id: item.limit_amount
        for item in budgets_service.list_budgets(session, month)
    }
    assert saved == {None: 10_000.0, products.id: 500.0}

    dashboard = client.get("/")
    assert "10\u00a0000,00" in dashboard.text  # общий лимит в прогресс-барах

    # 0 в поле = убрать лимит
    client.post(
        "/budgets",
        data={"month": month, "limit_overall": "0", f"limit_{products.id}": "500", "back": "/"},
        follow_redirects=True,
    )
    session.expire_all()
    assert [item.category_id for item in budgets_service.list_budgets(session, month)] == [
        products.id
    ]


def test_export_csv(client: TestClient, today_expense) -> None:
    response = client.get("/reports/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert 'attachment; filename="expenses_' in response.headers["content-disposition"]

    assert response.content.startswith(b"\xef\xbb\xbf")  # BOM для Excel
    text = response.content.decode("utf-8-sig")
    assert "Дата;Сумма;Валюта;Категория;Кто;Комментарий" in text
    assert "150,00" in text
    assert "Продукты" in text
    assert "Слава" in text
    assert "свежая трата" in text
    assert "Итого;150,00" in text


def test_reports_page_period_and_month_chart(
    client: TestClient, user, categories, add_expense
) -> None:
    add_expense(user, categories["Продукты"], 300.0, MARCH, "март")
    add_expense(user, categories["Транспорт"], 25.0, datetime(2024, 4, 2, 8, 0), "апрель")

    response = client.get("/reports", params={"start": "2024-03-01", "end": "2024-04-30"})
    assert response.status_code == 200
    assert "325,00" in response.text
    assert month_label("2024-03") in response.text  # таблица динамики по месяцам

    only_march = client.get("/reports", params={"start": "2024-03-01", "end": "2024-03-31"})
    assert "300,00" in only_march.text
    assert "325,00" not in only_march.text


def test_users_page_month_and_fallback(client: TestClient, user, categories, add_expense) -> None:
    add_expense(user, categories["Продукты"], 300.0, MARCH, "март")

    response = client.get("/users", params={"month": "2024-03"})
    assert response.status_code == 200
    assert "Слава" in response.text
    assert "300,00" in response.text

    fallback = client.get("/users", params={"month": "не месяц"})
    assert fallback.status_code == 200
    assert month_label(month_key()) in fallback.text


@pytest.mark.parametrize("path", PAGES)
def test_pages_do_not_leak_server_errors(client: TestClient, path: str) -> None:
    """Страницы не должны отдавать трейсбеки Jinja2 наружу."""
    text = client.get(path).text
    assert "Traceback" not in text
    assert "jinja2.exceptions" not in text


