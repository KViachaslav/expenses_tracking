"""Подключение к SQLite: engine, фабрика сессий, базовый класс моделей."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """Базовый класс всех ORM-моделей."""


def build_engine(database_url: str | None = None, *, echo: bool = False) -> Engine:
    """Создаёт engine. Для SQLite включаем foreign_keys и WAL."""
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def ensure_data_dir() -> None:
    """Создаёт каталог для файла БД (нужно для первого запуска на RPi)."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)


ensure_data_dir()

engine = build_engine()
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


@contextmanager
def session_scope(session_factory: sessionmaker = SessionLocal) -> Iterator[Session]:
    """Транзакционный контекст: commit при успехе, rollback при ошибке.

    Пример:
        with session_scope() as session:
            session.add(Expense(...))
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """Зависимость FastAPI: сессия на время запроса."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db(
    *,
    engine_: Engine | None = None,
    session_factory: sessionmaker | None = None,
    seed: bool | None = None,
) -> None:
    """Создаёт таблицы (если их нет) и наполняет справочник категорий."""
    # Импорт нужен, чтобы модели зарегистрировались в metadata.
    from app.models import Budget, Category, Expense, User  # noqa: F401
    from app.services.categories import seed_default_categories

    target_engine = engine_ or engine
    factory = session_factory or sessionmaker(bind=target_engine, expire_on_commit=False)
    Base.metadata.create_all(bind=target_engine)

    need_seed = settings.seed_default_categories if seed is None else seed
    if need_seed:
        with session_scope(factory) as session:
            seed_default_categories(session)
