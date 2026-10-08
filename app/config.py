"""Конфигурация приложения.

Все значения читаются из переменных окружения (файл `.env` в корне проекта,
см. `.env.example`). Единый объект `settings` используется и ботом, и веб-слоем.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# .env не обязателен: существующие переменные окружения имеют приоритет.
load_dotenv(dotenv_path=ENV_FILE)


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _int_tuple(value: str | None) -> tuple[int, ...]:
    """Разбирает строку вида "111111, 222222" в кортеж int."""
    if not value:
        return ()
    result: list[int] = []
    for chunk in value.replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            result.append(int(chunk))
        except ValueError:
            continue
    return tuple(result)


def _path(value: str | None, default: Path) -> Path:
    if not value or not value.strip():
        return default
    path = Path(value.strip()).expanduser()
    return path if path.is_absolute() else (BASE_DIR / path)


@dataclass(frozen=True)
class Settings:
    """Настройки приложения (immutable)."""

    base_dir: Path
    bot_token: str
    allowed_telegram_ids: tuple[int, ...]
    admin_telegram_ids: tuple[int, ...]
    db_path: Path
    web_host: str
    web_port: int
    tz: str
    default_currency: str
    log_level: str
    seed_default_categories: bool

    @property
    def database_url(self) -> str:
        """DSN для SQLAlchemy."""
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent

    @property
    def is_bot_configured(self) -> bool:
        return bool(self.bot_token)

    @property
    def admins(self) -> tuple[int, ...]:
        """Список админов: явные админы, иначе весь белый список."""
        return self.admin_telegram_ids or self.allowed_telegram_ids

    def is_allowed(self, telegram_id: int | None) -> bool:
        """Пускаем ли пользователя к боту.

        Если `ALLOWED_TELEGRAM_IDS` не задан — доступ открыт (удобно для отладки,
        в проде обязательно заполните белый список).
        """
        if telegram_id is None:
            return False
        if not self.allowed_telegram_ids:
            return True
        return telegram_id in self.allowed_telegram_ids

    def is_admin(self, telegram_id: int | None) -> bool:
        if telegram_id is None:
            return False
        admins = self.admins
        if not admins:
            return True
        return telegram_id in admins


def load_settings() -> Settings:
    """Собирает `Settings` из переменных окружения."""
    return Settings(
        base_dir=BASE_DIR,
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        allowed_telegram_ids=_int_tuple(os.getenv("ALLOWED_TELEGRAM_IDS")),
        admin_telegram_ids=_int_tuple(os.getenv("ADMIN_TELEGRAM_IDS")),
        db_path=_path(os.getenv("DB_PATH"), BASE_DIR / "data" / "expenses.db"),
        web_host=os.getenv("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0",
        web_port=_int(os.getenv("WEB_PORT"), 8080),
        tz=os.getenv("TZ", "Europe/Minsk").strip() or "Europe/Minsk",
        default_currency=(os.getenv("DEFAULT_CURRENCY", "BYN").strip() or "BYN").upper(),
        log_level=(os.getenv("LOG_LEVEL", "INFO").strip() or "INFO").upper(),
        seed_default_categories=_bool(os.getenv("SEED_DEFAULT_CATEGORIES"), True),
    )


settings = load_settings()
