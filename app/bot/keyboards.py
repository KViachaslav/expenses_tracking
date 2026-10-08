"""Клавиатуры Telegram-бота."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from app.models import Category

SKIP_COMMENT = "expense:skip_comment"
CANCEL = "expense:cancel"
# Префиксы callback_data
CATEGORY_PREFIX = "cat:"


def main_menu() -> ReplyKeyboardMarkup:
    """Основное меню (нижняя клавиатура)."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить трату"), KeyboardButton(text="📊 Сегодня")],
            [KeyboardButton(text="📅 За месяц"), KeyboardButton(text="🏆 Топ категорий")],
            [KeyboardButton(text="🗂 Категории"), KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Например: 500 продукты хлеб",
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    """Компактная клавиатура шага FSM."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
    )


def categories_inline(
    categories: Sequence[Category], *, columns: int = 2
) -> InlineKeyboardMarkup:
    """Инлайн-выбор категории."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for category in categories:
        row.append(
            InlineKeyboardButton(
                text=category.title,
                callback_data=f"{CATEGORY_PREFIX}{category.id}",
            )
        )
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=CANCEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def comment_inline() -> InlineKeyboardMarkup:
    """Кнопки на шаге ввода комментария."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Без комментария", callback_data=SKIP_COMMENT)],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=CANCEL)],
        ]
    )


def confirm_inline() -> InlineKeyboardMarkup:
    """Подтверждение быстрой траты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, записать", callback_data="quick:save")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="quick:cancel")],
        ]
    )
