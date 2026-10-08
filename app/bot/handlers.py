"""Хендлеры Telegram-бота: команды, FSM добавления траты, быстрый ввод."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.orm import Session

from app.bot import keyboards as kb
from app.bot.parser import QuickParseError, parse_amount, parse_quick_input
from app.config import settings
from app.formatting import format_money, format_percent, plural_ru
from app.models import Category, Expense, User
from app.schemas import BudgetProgress, PeriodComparison
from app.services import budgets as budgets_service
from app.services import categories as categories_service
from app.services import stats
from app.services.expenses import add_expense, ensure_user
from app.timeutils import (
    day_bounds,
    month_bounds,
    month_key,
    month_label,
    previous_month_bounds,
)

logger = logging.getLogger(__name__)
router = Router(name="expenses")

# Тексты кнопок основного меню
BTN_ADD = "➕ Добавить трату"
BTN_TODAY = "📊 Сегодня"
BTN_MONTH = "📅 За месяц"
BTN_TOP = "🏆 Топ категорий"
BTN_CATEGORIES = "🗂 Категории"
BTN_HELP = "❓ Помощь"
BTN_CANCEL = "❌ Отмена"

HELP_TEXT = (
    "<b>Как пользоваться</b>\n\n"
    "🧾 <b>Быстрый ввод</b> — просто отправьте сообщение:\n"
    "   <code>500 продукты хлеб и молоко</code>\n"
    "   Сумма, категория (по названию или синониму) и комментарий.\n\n"
    "Команды:\n"
    "/add — пошаговое добавление траты\n"
    "/today — расходы за сегодня\n"
    "/month — отчёт за текущий месяц\n"
    "/stats — топ категорий за месяц\n"
    "/categories — список категорий\n"
    "/addcat Название | 🎁 | синоним,синоним — добавить категорию (админ)\n"
    "/cancel — отменить текущее действие\n"
    "/id — узнать свой telegram_id"
)


class AddExpense(StatesGroup):
    """Состояния пошагового добавления траты."""

    amount = State()
    category = State()
    comment = State()


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #
def _ensure_bot_user(source: Message | CallbackQuery, session: Session) -> User:
    """Регистрирует/обновляет пользователя по данным Telegram."""
    sender = source.from_user
    if sender is None:  # pragma: no cover - апдейты без from_user не приходят
        raise ValueError("В апдейте нет from_user")
    return ensure_user(
        session, sender.id, username=sender.username, full_name=sender.full_name
    )


async def _reply(source: Message | CallbackQuery, text: str, **kwargs: object) -> None:
    """Отправляет сообщение из хендлера message или callback."""
    if isinstance(source, CallbackQuery):
        if isinstance(source.message, Message):
            await source.message.answer(text, **kwargs)
        else:  # pragma: no cover - недоступное сообщение
            await source.answer(text[:200])
    else:
        await source.answer(text, **kwargs)


def _text_bar(value: float, maximum: float, width: int = 10) -> str:
    """Простой текстовый прогресс-бар."""
    if maximum <= 0 or value <= 0:
        return "░" * width
    filled = max(1, min(width, round(value / maximum * width)))
    return "▓" * filled + "░" * (width - filled)


def _top_categories_text(items: list) -> str:
    if not items:
        return "Пока нет данных за этот период."
    maximum = items[0].total or 1.0
    lines: list[str] = []
    for item in items:
        lines.append(
            f"{_text_bar(item.total, maximum)} {item.title} — "
            f"<b>{format_money(item.total)}</b> ({format_percent(item.share)})"
        )
    return "\n".join(lines)


def _summary_text(title: str, data, comparison=None) -> str:
    words = plural_ru(data.count, ("трата", "траты", "трат"))
    lines = [
        f"<b>{title}</b>",
        f"💰 Всего: <b>{format_money(data.total)}</b>",
        f"🧾 {data.count} {words} · в среднем {format_money(data.avg_per_day)}/день",
    ]
    if comparison is not None and comparison.delta_percent is not None:
        arrow = "🔺" if comparison.delta > 0 else "🔻"
        lines.append(
            f"{arrow} к прошлому периоду: {format_percent(comparison.delta_percent)} "
            f"({format_money(abs(comparison.delta))})"
        )
    return "\n".join(lines)


def _saved_text(expense: Expense, category: Category, user: User | None = None) -> str:
    parts = [
        "✅ Записано",
        f"💵 <b>{format_money(expense.amount, expense.currency)}</b>",
        f"🗂 {category.title}",
    ]
    if expense.comment:
        parts.append(f"💬 {expense.comment}")
    if user is not None:
        parts.append(f"👤 {user.display_name}")
    parts.append(f"🗓 {expense.spent_at.strftime('%d.%m.%Y %H:%M')}")
    return "\n".join(parts)


async def _ask_category(source: Message | CallbackQuery, state: FSMContext, session: Session) -> None:
    """Показывает список категорий для выбора."""
    available = categories_service.list_categories(session)
    if not available:
        await state.clear()
        await _reply(
            source,
            "Нет доступных категорий. Добавьте их в веб-интерфейсе или командой /addcat.",
            reply_markup=kb.main_menu(),
        )
        return
    await state.set_state(AddExpense.category)
    await _reply(
        source,
        "🗂 Выберите категорию или напишите её название:",
        reply_markup=kb.categories_inline(available),
    )


async def _save_from_state(
    source: Message | CallbackQuery,
    state: FSMContext,
    session: Session,
    *,
    comment: str | None,
) -> None:
    """Сохраняет трату из данных FSM."""
    data = await state.get_data()
    category = categories_service.get_category(session, data.get("category_id"))
    if category is None:
        await state.clear()
        await _reply(
            source, "Категория не найдена. Начните заново: /add", reply_markup=kb.main_menu()
        )
        return

    user = _ensure_bot_user(source, session)
    expense = add_expense(
        session,
        user=user,
        category=category,
        amount=float(data.get("amount") or 0),
        comment=comment,
        currency=data.get("currency"),
    )
    await state.clear()
    await _reply(source, _saved_text(expense, category, user), reply_markup=kb.main_menu())


# --------------------------------------------------------------------------- #
# Команды
# --------------------------------------------------------------------------- #
@router.message(CommandStart())
async def cmd_start(message: Message, session: Session, state: FSMContext) -> None:
    user = _ensure_bot_user(message, session)
    await state.clear()
    await message.answer(
        f"👋 Привет, <b>{user.display_name}</b>!\n\n"
        "Я помогу записывать домашние расходы. Самый быстрый способ — одно сообщение:\n"
        "<code>500 продукты хлеб и молоко</code>\n\n"
        "Или просто нажмите «➕ Добавить трату».\n\n"
        "Статистика доступна в боте (<b>/month</b>, <b>/stats</b>) и в веб-интерфейсе.",
        reply_markup=kb.main_menu(),
    )


@router.message(StateFilter(None), Command("help"))
@router.message(StateFilter(None), F.text == BTN_HELP)
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=kb.main_menu())


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"Ваш telegram_id: <code>{message.from_user.id}</code>")


@router.message(StateFilter(None), Command("add"))
@router.message(StateFilter(None), F.text == BTN_ADD)
async def cmd_add(message: Message, state: FSMContext) -> None:
    await state.set_state(AddExpense.amount)
    await state.update_data(amount=None, currency=None, category_id=None, comment=None)
    await message.answer(
        "💵 Введите сумму траты (например <code>500</code> или <code>500,50</code>):",
        reply_markup=kb.cancel_menu(),
    )


# Отмена регистрируется ДО шагов FSM: иначе текст «❌ Отмена» попадёт в шаг ввода.
@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    text = "Действие отменено." if current else "Нечего отменять 🙂"
    await message.answer(text, reply_markup=kb.main_menu())


@router.callback_query(F.data == kb.CANCEL)
async def cancel_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Отменено")
    await state.clear()
    await _reply(callback, "Действие отменено.", reply_markup=kb.main_menu())


# --------------------------------------------------------------------------- #
# FSM: пошаговое добавление
# --------------------------------------------------------------------------- #
@router.message(AddExpense.amount, F.text)
async def step_amount(message: Message, state: FSMContext, session: Session) -> None:
    try:
        amount, currency = parse_amount(message.text or "")
    except QuickParseError:
        await message.answer("🤔 Не понял сумму. Напишите число, например <code>500</code>:")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля 🙂")
        return

    await state.update_data(amount=amount, currency=currency)
    await _ask_category(message, state, session)


@router.callback_query(AddExpense.category, F.data.startswith(kb.CATEGORY_PREFIX))
async def step_category_callback(
    callback: CallbackQuery, state: FSMContext, session: Session
) -> None:
    raw = (callback.data or "")[len(kb.CATEGORY_PREFIX) :]
    category = categories_service.get_category(session, int(raw)) if raw.isdigit() else None
    if category is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    await callback.answer()
    await state.update_data(category_id=category.id)
    await state.set_state(AddExpense.comment)
    await _reply(
        callback,
        f"🗂 {category.title}\n\n💬 Добавьте комментарий или нажмите «Без комментария»:",
        reply_markup=kb.comment_inline(),
    )


@router.message(AddExpense.category, F.text)
async def step_category_text(message: Message, state: FSMContext, session: Session) -> None:
    category = categories_service.find_category(session, message.text)
    if category is None:
        await message.answer(
            "Не нашёл такую категорию. Попробуйте ещё раз:",
            reply_markup=kb.categories_inline(categories_service.list_categories(session)),
        )
        return

    await state.update_data(category_id=category.id)
    await state.set_state(AddExpense.comment)
    await message.answer(
        f"🗂 {category.title}\n\n💬 Добавьте комментарий или нажмите «Без комментария»:",
        reply_markup=kb.comment_inline(),
    )


@router.message(AddExpense.comment, F.text)
async def step_comment(message: Message, state: FSMContext, session: Session) -> None:
    comment = (message.text or "").strip()
    if comment.lower() in {"-", "нет", "без комментария", "пропустить", "skip"}:
        comment = ""
    await _save_from_state(message, state, session, comment=comment or None)


@router.callback_query(AddExpense.comment, F.data == kb.SKIP_COMMENT)
async def step_comment_skip(
    callback: CallbackQuery, state: FSMContext, session: Session
) -> None:
    await callback.answer()
    await _save_from_state(callback, state, session, comment=None)


# --------------------------------------------------------------------------- #
# Отчёты
# --------------------------------------------------------------------------- #
@router.message(StateFilter(None), Command("today"))
@router.message(StateFilter(None), F.text == BTN_TODAY)
async def cmd_today(message: Message, session: Session) -> None:
    start, end = day_bounds()
    data = stats.summary(session, start, end)
    text = _summary_text(f"Расходы за {start.strftime('%d.%m.%Y')}", data)

    expenses = stats.fetch_expenses(session, start=start, end=end, limit=15)
    if expenses:
        lines = ["", "<b>Последние записи</b>"]
        for expense in expenses:
            category = expense.category
            title = category.title if category else "—"
            who = f" · {expense.user.display_name}" if expense.user else ""
            comment = f" — {expense.comment}" if expense.comment else ""
            lines.append(
                f"• {expense.spent_at.strftime('%H:%M')} · "
                f"<b>{format_money(expense.amount, expense.currency)}</b> · {title}{comment}{who}"
            )
        text += "\n".join(lines)
    await message.answer(text, reply_markup=kb.main_menu())


@router.message(StateFilter(None), Command("month"))
@router.message(StateFilter(None), F.text == BTN_MONTH)
async def cmd_month(message: Message, session: Session) -> None:
    key = month_key()
    start, end = month_bounds(key)
    data = stats.summary(session, start, end)

    prev_start, prev_end = previous_month_bounds(key)
    previous_total = stats.summary(session, prev_start, prev_end).total
    delta = round(data.total - previous_total, 2)
    comparison = PeriodComparison(
        current_total=data.total,
        previous_total=previous_total,
        delta=delta,
        delta_percent=round(delta / previous_total * 100, 1) if previous_total else None,
    )

    text = _summary_text(f"Расходы за {month_label(key)}", data, comparison)
    top = stats.top_categories(session, start, end, limit=5)
    text += "\n\n<b>Топ категорий</b>\n" + _top_categories_text(top)

    progress = budgets_service.budget_progress(session, key)
    if progress:
        text += "\n\n<b>🎯 Бюджеты</b>\n" + "\n".join(_budget_line(item) for item in progress)
    await message.answer(text, reply_markup=kb.main_menu())


@router.message(StateFilter(None), Command("stats", "top"))
@router.message(StateFilter(None), F.text == BTN_TOP)
async def cmd_stats(message: Message, session: Session) -> None:
    key = month_key()
    start, end = month_bounds(key)
    items = stats.category_totals(session, start, end)
    text = f"<b>🏆 Топ категорий за {month_label(key)}</b>\n\n" + _top_categories_text(items[:10])

    people = [item for item in stats.user_totals(session, start, end) if item.total]
    if len(people) > 1:
        text += "\n\n<b>👥 Кто сколько потратил</b>\n" + "\n".join(
            f"• {item.display_name} — <b>{format_money(item.total)}</b> "
            f"({format_percent(item.share)})"
            for item in people
        )
    await message.answer(text, reply_markup=kb.main_menu())


@router.message(StateFilter(None), Command("categories", "cats"))
@router.message(StateFilter(None), F.text == BTN_CATEGORIES)
async def cmd_categories(message: Message, session: Session) -> None:
    start, end = month_bounds()
    used = {item.category_id: item for item in stats.category_totals(session, start, end)}
    lines: list[str] = []
    for category in categories_service.list_categories(session):
        item = used.get(category.id)
        spent = f"<b>{format_money(item.total)}</b>" if item else "—"
        count = f"{item.count} шт." if item else "нет трат"
        lines.append(f"{category.title} — {spent} ({count})")
    if not lines:
        lines.append("Категорий пока нет.")
    await message.answer(
        f"<b>🗂 Категории · {month_label()}</b>\n" + "\n".join(lines),
        reply_markup=kb.main_menu(),
    )


@router.message(StateFilter(None), Command("budget"))
async def cmd_budget(message: Message, session: Session) -> None:
    progress = budgets_service.budget_progress(session, month_key())
    if not progress:
        await message.answer(
            "Бюджеты на этот месяц не заданы. Их можно настроить в веб-интерфейсе.",
            reply_markup=kb.main_menu(),
        )
        return
    text = f"<b>🎯 Бюджеты на {month_label()}</b>\n" + "\n".join(
        _budget_line(item) for item in progress
    )
    await message.answer(text, reply_markup=kb.main_menu())


@router.message(StateFilter(None), Command("addcat"))
async def cmd_addcat(message: Message, command: CommandObject, session: Session) -> None:
    if not settings.is_admin(message.from_user.id):
        await message.answer("Добавлять категории может только администратор 🙂")
        return

    args = (command.args or "").strip()
    if not args:
        await message.answer(
            "Формат: <code>/addcat Название | 🎁 | синоним,синоним</code>\n"
            "Эмодзи и синонимы можно не указывать.",
        )
        return

    parts = [part.strip() for part in args.split("|")]
    name = parts[0]
    emoji = parts[1] if len(parts) > 1 and parts[1] else None
    synonyms = parts[2] if len(parts) > 2 else ""
    if emoji is None:  # «/addcat Такси 🚕» — эмодзи вторым словом
        words = name.split()
        if len(words) > 1 and len(words[-1]) <= 3:
            name, emoji = " ".join(words[:-1]), words[-1]

    try:
        category = categories_service.create_category(
            session, name, emoji=emoji, synonyms=synonyms
        )
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    await message.answer(f"✅ Категория добавлена: <b>{category.title}</b>")


def _budget_line(item: BudgetProgress) -> str:
    """Строка прогресса бюджета с индикатором расхода."""
    mark = "🔴" if item.over else ("🟡" if item.percent >= 80 else "🟢")
    rest = (
        f"перерасход {format_money(abs(item.remaining))}"
        if item.over
        else f"осталось {format_money(item.remaining)}"
    )
    return (
        f"{mark} {item.title} — <b>{format_money(item.spent)}</b> "
        f"из {format_money(item.limit_amount)} ({format_percent(item.percent)}) · {rest}"
    )


# --------------------------------------------------------------------------- #
# Быстрый ввод текстом
# --------------------------------------------------------------------------- #
@router.message(StateFilter(None), F.text)
async def quick_input(message: Message, state: FSMContext, session: Session) -> None:
    """«500 продукты хлеб» — сумма, категория и комментарий одной строкой."""
    text = (message.text or "").strip()
    if text.startswith("/"):
        await message.answer("Неизвестная команда. Список команд: /help")
        return

    try:
        parsed = parse_quick_input(text, categories_service.parser_keywords(session))
    except QuickParseError:
        await message.answer(
            "🤔 Не понял сообщение. Формат: <code>500 продукты хлеб</code>\nСправка: /help"
        )
        return

    user = _ensure_bot_user(message, session)
    category = (
        categories_service.find_category(session, parsed.category) if parsed.category else None
    )
    if category is None:
        # Сумма распознана, категория — нет: продолжаем диалог.
        await state.update_data(
            amount=parsed.amount, currency=parsed.currency, comment=parsed.comment
        )
        await message.answer(
            f"💰 {format_money(parsed.amount, parsed.currency)} — осталось выбрать категорию."
        )
        await _ask_category(message, state, session)
        return

    expense = add_expense(
        session,
        user=user,
        category=category,
        amount=parsed.amount,
        comment=parsed.comment,
        currency=parsed.currency,
    )
    await message.answer(_saved_text(expense, category, user), reply_markup=kb.main_menu())


@router.message(StateFilter("*"), F.text.startswith("/"))
async def unknown_command_in_state(message: Message) -> None:
    """Команда во время пошагового ввода: не теряем данные молча."""
    await message.answer(
        "Сейчас идёт ввод траты. Завершите его (или /cancel) и повторите команду 🙂"
    )

