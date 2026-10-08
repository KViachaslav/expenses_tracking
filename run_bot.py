"""Точка входа Telegram-бота: `python run_bot.py` (или `python -m app.bot.main`).

Требуется только `BOT_TOKEN` в `.env` (см. README.md, раздел «Настройка .env»).
"""

from __future__ import annotations

from app.bot.main import main

if __name__ == "__main__":
    main()
