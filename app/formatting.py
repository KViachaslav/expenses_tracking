"""Форматирование значений для вывода (Telegram и Jinja2-шаблоны)."""

from __future__ import annotations

from datetime import date, datetime

from app.config import settings

CURRENCY_SIGNS = {"BYN": "Br", "RUB": "₽", "USD": "$", "EUR": "€", "UAH": "₴", "KZT": "₸"}


def format_money(amount: float | int | None, currency: str | None = None, *, decimals: int = 2) -> str:
    """1234.5 -> '1 234,50 BYN' (разряды — пробелом, десятичный разделитель — запятая)."""
    if amount is None:
        amount = 0.0
    text = f"{float(amount):,.{decimals}f}".replace(",", "\u00a0").replace(".", ",")
    code = (currency or settings.default_currency).upper()
    return f"{text} {code}"


def format_amount(amount: float | int | None, *, decimals: int = 2) -> str:
    """Только число, без кода валюты."""
    if amount is None:
        amount = 0.0
    return f"{float(amount):,.{decimals}f}".replace(",", "\u00a0").replace(".", ",")


def format_date(value: date | datetime | str | None, fmt: str = "%d.%m.%Y") -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(fmt)


def format_datetime(value: date | datetime | str | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    return format_date(value, fmt)


def format_percent(value: float | None, *, decimals: int = 0) -> str:
    if value is None:
        return "—"
    text = f"{float(value):.{decimals}f}".replace(".", ",")
    return f"{text}%"


def plural_ru(count: float | int, forms: tuple[str, str, str]) -> str:
    """forms = ('трата', 'траты', 'трат')."""
    number = abs(int(count)) % 100
    if 11 <= number <= 14:
        return forms[2]
    number %= 10
    if number == 1:
        return forms[0]
    if 2 <= number <= 4:
        return forms[1]
    return forms[2]
