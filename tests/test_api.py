"""Тесты JSON API (`app.web.api.routes`) через TestClient."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services import budgets as budgets_service
from app.services import expenses as expenses_service
from app.timeutils import month_key, today

TELEGRAM_ID = 555_000


@pytest.fixture
def api_user(session: Session) -> object:
    """Пользователь, «зарегистрированный» ботом (есть telegram_id)."""
    user = expenses_service.ensure_user(session, TELEGRAM_ID, username="anna", full_name="Анна")
    session.commit()
    return user


@pytest.fixture
def api_expense(client: TestClient, api_user) -> dict:
    """Трата, созданная через API (сегодня, чтобы попала в отчёты за месяц)."""
    response = client.post(
        "/api/expenses",
        json={
            "amount": 199.99,
            "category_name": "Продукты",
            "telegram_id": TELEGRAM_ID,
            "comment": "из api",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["currency"] == "BYN"
    assert payload["categories"] == 8
    assert payload["month"] == month_key()


def test_openapi_and_docs(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_create_expense_stores_row(
    client: TestClient, session: Session, api_user, api_expense: dict
) -> None:
    assert api_expense["amount"] == 199.99
    assert api_expense["currency"] == "BYN"
    assert api_expense["comment"] == "из api"
    assert api_expense["category"]["name"] == "Продукты"
    assert api_expense["user"]["telegram_id"] == TELEGRAM_ID
    assert api_expense["spent_at"].startswith(today().isoformat())

    rows = client.get("/api/expenses").json()
    assert [item["id"] for item in rows] == [api_expense["id"]]


def test_create_expense_case_insensitive_category_and_spent_at(
    client: TestClient, api_user, api_expense: dict
) -> None:
    response = client.post(
        "/api/expenses",
        json={
            "amount": 10,
            "category_name": "пРОДУКТЫ",
            "user_id": api_user.id,
            "spent_at": "2024-03-10T12:30:00",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["category"]["name"] == "Продукты"
    assert payload["spent_at"].startswith("2024-03-10T12:30")


def test_create_expense_errors(client: TestClient, api_user) -> None:
    unknown_category = client.post(
        "/api/expenses",
        json={"amount": 10, "category_name": "Нет такой", "telegram_id": TELEGRAM_ID},
    )
    assert unknown_category.status_code == 404

    unknown_user = client.post(
        "/api/expenses",
        json={"amount": 10, "category_name": "Продукты", "telegram_id": 777_777},
    )
    assert unknown_user.status_code == 404

    zero_amount = client.post(
        "/api/expenses",
        json={"amount": 0, "category_name": "Продукты", "telegram_id": TELEGRAM_ID},
    )
    assert zero_amount.status_code == 422

    no_author = client.post("/api/expenses", json={"amount": 10, "category_name": "Продукты"})
    assert no_author.status_code == 422


def test_delete_expense(client: TestClient, api_expense: dict) -> None:
    deleted = client.delete(f"/api/expenses/{api_expense['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/expenses").json() == []
    assert client.delete(f"/api/expenses/{api_expense['id']}").status_code == 404


def test_list_expenses_filters(client: TestClient, api_user, api_expense: dict, session: Session) -> None:
    transport = None
    for item in client.get("/api/categories").json():
        if item["name"] == "Транспорт":
            transport = item
    assert transport is not None

    client.post(
        "/api/expenses",
        json={
            "amount": 50,
            "category_id": transport["id"],
            "telegram_id": TELEGRAM_ID,
            "comment": "taxi домой",
        },
    )

    assert len(client.get("/api/expenses").json()) == 2
    only_transport = client.get(f"/api/expenses?category_id={transport['id']}").json()
    assert [item["amount"] for item in only_transport] == [50.0]
    assert [item["comment"] for item in client.get("/api/expenses?search=API").json()] == ["из api"]
    assert client.get(f"/api/expenses?user_id={api_user.id}").json()
    assert client.get("/api/expenses?limit=1").json()
    assert client.get("/api/expenses?start=2020-01-01&end=2020-01-31").json() == []
    assert client.get("/api/expenses?limit=0").status_code == 422
