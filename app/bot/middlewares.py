"""Middleware бота: сессия БД на каждый апдейт и белый список пользователей."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, settings

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию SQLAlchemy и прокидывает её в хендлеры как data['session']."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: Session = self.session_factory()
        data["session"] = session
        data.setdefault("settings", settings)
        try:
            result = await handler(event, data)
            session.commit()
            return result
        except Exception:
            session.rollback()
            logger.exception("Ошибка при обработке апдейта — транзакция отменена")
            raise
        finally:
            session.close()


class AccessMiddleware(BaseMiddleware):
    """Пускает к боту только telegram_id из ALLOWED_TELEGRAM_IDS (если список задан)."""

    def __init__(self, config: Settings | None = None) -> None:
        self.config = config or settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        telegram_id = getattr(user, "id", None)
        if self.config.is_allowed(telegram_id):
            return await handler(event, data)

        logger.warning("Отклонён доступ для telegram_id=%s", telegram_id)
        text = (
            "🔒 У вас нет доступа к этому боту.\n"
            f"Ваш telegram_id: <code>{telegram_id}</code>\n"
            "Попросите администратора добавить его в ALLOWED_TELEGRAM_IDS."
        )
        if isinstance(event, CallbackQuery):
            await event.answer("Нет доступа", show_alert=True)
        elif isinstance(event, Message):
            await event.answer(text)
        return None
