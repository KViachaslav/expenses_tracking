"""Общие фикстуры pytest.

ВАЖНО: переменные окружения подменяются ДО импорта `app.*`, потому что
`app.config.settings` и `app.database.engine` создаются один раз при импорте.
БД тестов — временный файл SQLite (рабочая `data/expenses.db` не затрагивается).

Запуск:
    pytest
    pytest tests/test_api.py -q
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="zatrats_tests_"))
TEST_DB = _TMP_DIR / "test.db"

os.environ["DB_PATH"] = TEST_DB.as_posix()
os.environ["SEED_DEFAULT_CATEGORIES"] = "1"
os.environ.setdefault("BOT_TOKEN", "000000:test-token")

from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import Category, Expense, User  # noqa: E402
from app.services import categories as categories_service  # noqa: E402
from app.services import expenses as expenses_service  # noqa: E402
from app.web.routes import app as web_app  # noqa: E402

AddExpense = Callable[..., Expense]


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    """Перед каждым тестом: пустая схема + категории по умолчанию."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        categories_service.seed_default_categories(session)
        session.commit()
    yield


@pytest.fixture
def session() -> Iterator[Session]:
    """Сессия БД теста (данные нужно коммитить явно)."""
    with SessionLocal() as db_session:
        yield db_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Тестовый HTTP-клиент веб-приложения (со запуском lifespan)."""
    with TestClient(web_app) as test_client:
        yield test_client


@pytest.fixture
def users(session: Session) -> list[User]:
    """Два члена семьи."""
    first = expenses_service.ensure_user(
        session, 111_111, username="slava", full_name="Слава"
    )
    second = expenses_service.ensure_user(
        session, 222_222, username="masha", full_name="Маша"
    )
    session.commit()
    return [first, second]


@pytest.fixture
def user(users: list[User]) -> User:
    """Первый член семьи (для тестов, где важен один автор)."""
    return users[0]


@pytest.fixture
def categories(session: Session) -> dict[str, Category]:
    """Категории по умолчанию, разложенные по названию."""
    return {item.name: item for item in categories_service.list_categories(session)}


@pytest.fixture
def add_expense(session: Session) -> Callable[..., Expense]:
    """Фабрика трат: add_expense(user, category, amount, spent_at, comment)."""

    def _add(
        owner: User,
        category: Category,
        amount: float,
        spent_at: datetime | None = None,
        comment: str | None = None,
        **kwargs: object,
    ) -> Expense:
        expense = expenses_service.add_expense(
            session,
            user=owner,
            category=category,
            amount=amount,
            comment=comment,
            spent_at=spent_at,
            **kwargs,  # type: ignore[arg-type]
        )
        session.commit()
        return expense

    return _add


@pytest.fixture
def today_expense(
    add_expense: Callable[..., Expense], user: User, categories: dict[str, Category]
) -> Expense:
    """Одна трата «сегодня» — чтобы страницы текущего месяца были непустыми."""
    from app.timeutils import local_now

    return add_expense(user, categories["Продукты"], 150.0, local_now(), "свежая трата")


def make_day(value: str | date) -> date:
    """'2024-03-10' -> date (мелкий хелпер для тестов статистики)."""
    return value if isinstance(value, date) else date.fromisoformat(value)
