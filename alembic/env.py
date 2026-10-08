"""Окружение Alembic для проекта «Семейные расходы».

URL базы берётся из настроек приложения (`app.config.settings`, то есть из
переменной окружения `DB_PATH` или `.env`), поэтому миграции применяются ровно
к тому файлу SQLite, с которым работают бот и веб-сервис.

Переопределить URL можно двумя способами:
    * `ALEMBIC_DATABASE_URL=sqlite:///path/to.db` в окружении;
    * `cfg.set_main_option("sqlalchemy.url", ...)` или
      `cfg.attributes["sqlalchemy_url"] = ...` (используется в тестах).
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Корень проекта в sys.path — чтобы `alembic` работал при запуске из любого каталога.
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app import models  # noqa: E402,F401  (регистрирует таблицы в metadata)
from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """Приоритет: attributes -> alembic.ini -> ALEMBIC_DATABASE_URL -> настройки."""
    override = config.attributes.get("sqlalchemy_url")
    if override:
        return str(override)
    ini_url = (config.get_main_option("sqlalchemy.url") or "").strip()
    if ini_url:
        return ini_url
    return os.getenv("ALEMBIC_DATABASE_URL") or settings.database_url


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Режим `--sql`: генерируем SQL без подключения к БД."""
    url = database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=is_sqlite(url),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Обычный режим: применяем миграции к реальной БД."""
    url = database_url()
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite(url),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
