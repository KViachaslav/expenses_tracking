"""Точка входа Telegram-бота: `python -m app.bot.main` или `python run_bot.py`."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.bot import handlers
from app.bot.middlewares import AccessMiddleware, DbSessionMiddleware
from app.config import settings
from app.database import SessionLocal, init_db, session_scope
from app.services.categories import seed_default_categories

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="add", description="Добавить трату"),
    BotCommand(command="today", description="Расходы за сегодня"),
    BotCommand(command="month", description="Отчёт за месяц"),
    BotCommand(command="stats", description="Топ категорий"),
    BotCommand(command="categories", description="Категории"),
    BotCommand(command="budget", description="Бюджеты месяца"),
    BotCommand(command="cancel", description="Отменить действие"),
    BotCommand(command="help", description="Помощь"),
]


def configure_logging(level: str | None = None) -> None:
    logging.basicConfig(
        level=getattr(logging, (level or settings.log_level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def setup_database() -> None:
    """Создаёт файл БД, таблицы и категории по умолчанию."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    if settings.seed_default_categories:
        with session_scope() as session:
            created = seed_default_categories(session)
        if created:
            logger.info("Добавлено категорий по умолчанию: %s", created)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.message.middleware(DbSessionMiddleware(SessionLocal))
    dispatcher.callback_query.middleware(DbSessionMiddleware(SessionLocal))
    dispatcher.message.middleware(AccessMiddleware(settings))
    dispatcher.callback_query.middleware(AccessMiddleware(settings))
    dispatcher.include_router(handlers.router)
    return dispatcher


async def run() -> None:
    if not settings.is_bot_configured:
        raise SystemExit("BOT_TOKEN не задан: скопируйте .env.example в .env и впишите токен.")

    configure_logging()
    setup_database()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = create_dispatcher()
    await bot.set_my_commands(BOT_COMMANDS)

    logger.info("Бот запущен. Разрешённые пользователи: %s", settings.allowed_telegram_ids or "все")
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code:
            logger.error("%s", exc.code)
            raise
        logger.info("Бот остановлен")


if __name__ == "__main__":
    main()
