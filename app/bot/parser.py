"""Разбор быстрого ввода одной строкой.

Пример::

    "500 продукты хлеб и молоко"
    -> сумма 500, категория «Продукты», комментарий «хлеб и молоко»

Модуль не работает с БД: список категорий (пары «название, ключевое слово»)
передаётся снаружи, поэтому парсер легко тестировать.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

# 500 | 500,50 | 1 500.25
NUMBER_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d{1,2})?$")

CURRENCY_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("byn", "BYN"),
    ("белруб", "BYN"),
    ("rub", "RUB"),
    ("руб", "RUB"),
    ("грн", "UAH"),
    ("uah", "UAH"),
    ("usd", "USD"),
    ("eur", "EUR"),
    ("р.", "RUB"),
    ("br", "BYN"),
    ("р", "RUB"),
    ("$", "USD"),
    ("€", "EUR"),
    ("₽", "RUB"),
)

_FUZZY_MIN_PREFIX = 5  # минимальная длина префикса для «мягкого» совпадения
_MIN_TOKEN_FOR_FUZZY = 4
_TRIM_CHARS = ".,;:!?()\"'«»—-"


class QuickParseError(ValueError):
    """Не удалось разобрать строку быстрого ввода."""


@dataclass(frozen=True)
class ParsedExpense:
    """Результат разбора быстрого ввода."""

    amount: float
    currency: str | None = None
    category: str | None = None
    comment: str | None = None
    raw: str = ""


def normalize_token(token: str) -> str:
    """Приводит слово к нижнему регистру и убирает лишнюю пунктуацию."""
    return token.strip().lower().strip(_TRIM_CHARS)


def tokenize(text: str) -> list[str]:
    """Разбивает строку на токены, сохраняя порядок."""
    return [chunk for chunk in re.split(r"\s+", (text or "").strip()) if chunk]


def parse_amount_token(token: str) -> tuple[float, str | None] | None:
    """Разбирает один токен как сумму. '500,50р' -> (500.5, 'RUB')."""
    text = normalize_token(token)
    if not text:
        return None

    currency: str | None = None
    for suffix, code in CURRENCY_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            candidate = text[: -len(suffix)].strip()
            if candidate and NUMBER_RE.match(candidate):
                text, currency = candidate, code
                break

    if not NUMBER_RE.match(text):
        return None
    return _to_float(text), currency


def parse_amount(text: str) -> tuple[float, str | None]:
    """Разбирает ответ пользователя «сумма» в FSM. Бросает QuickParseError."""
    tokens = tokenize(text)
    for index in range(len(tokens)):
        parsed = parse_amount_at(tokens, index)
        if parsed is not None:
            amount, currency, _consumed = parsed
            return amount, currency
    raise QuickParseError(f"Не похоже на сумму: {text!r}")


def parse_amount_at(tokens: list[str], index: int) -> tuple[float, str | None, int] | None:
    """Разбирает сумму начиная с токена `index`, склеивая группы разрядов.

    Возвращает (сумма, валюта, сколько токенов израсходовано) или None.
    Берём самое длинное разумное совпадение, потому что пробел — это и
    разделитель разрядов, и разделитель слов::

        "1 500" -> (1500.0, None, 2)
        "7 654,32 руб" -> (7654.32, "RUB", 3)
    """
    for size in (3, 2, 1):
        if index + size > len(tokens):
            continue
        parsed = parse_amount_token(" ".join(tokens[index : index + size]))
        if parsed:
            return parsed[0], parsed[1], size
    return None


def _to_float(text: str) -> float:
    clean = text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(round(Decimal(clean), 2))
    except InvalidOperation as exc:  # pragma: no cover - защита
        raise QuickParseError(f"Некорректная сумма: {text!r}") from exc


def build_index(
    keywords: Iterable[tuple[str, str]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Строит индексы (точных совпадений и префиксов) из пар «категория, слово»."""
    exact: dict[str, str] = {}
    prefixes: dict[str, str] = {}
    for category_name, keyword in keywords:
        key = (keyword or "").strip().lower()
        if not key:
            continue
        exact.setdefault(key, category_name)
        for size in range(_FUZZY_MIN_PREFIX, len(key)):
            prefixes.setdefault(key[:size], category_name)
    return exact, prefixes


def _lookup(token: str, exact: dict[str, str], prefixes: dict[str, str]) -> str | None:
    key = normalize_token(token)
    if not key:
        return None
    if key in exact:
        return exact[key]
    if len(key) >= _MIN_TOKEN_FOR_FUZZY:
        if key in prefixes:
            return prefixes[key]
        if len(key) >= _FUZZY_MIN_PREFIX and key[:_FUZZY_MIN_PREFIX] in prefixes:
            return prefixes[key[:_FUZZY_MIN_PREFIX]]
    return None


def match_category(
    tokens: list[str], exact: dict[str, str], prefixes: dict[str, str]
) -> tuple[int, int, str] | None:
    """Ищет самое раннее и самое длинное совпадение категории в токенах.

    Возвращает (начало, конец_не_включительно, название категории) или None.
    """
    total = len(tokens)
    for start in range(total):
        for size in range(min(3, total - start), 0, -1):
            phrase = normalize_token(" ".join(tokens[start : start + size]))
            name = exact.get(phrase)
            if name is None and size == 1:
                name = _lookup(tokens[start], exact, prefixes)
            if not name:
                continue
            end = start + size
            # Забираем идущие следом токены той же категории («мобильная связь»).
            while end < total and _lookup(tokens[end], exact, prefixes) == name:
                end += 1
            return start, end, name
    return None


def parse_quick_input(
    text: str,
    categories: Iterable[tuple[str, str]] | None = None,
) -> ParsedExpense:
    """Разбирает строку быстрого ввода.

    `categories` — пары (название категории, ключевое слово/синоним).
    Если не переданы, категория не распознаётся, а текст после суммы
    попадает в комментарий.
    """
    raw = (text or "").strip()
    if not raw:
        raise QuickParseError("Пустое сообщение")

    tokens = tokenize(raw)
    amount: float | None = None
    currency: str | None = None
    after: list[str] = []
    before: list[str] = []

    index = 0
    while index < len(tokens):
        # «1 500» и «7 654,32 руб» — сумма может быть разбита пробелами
        parsed = parse_amount_at(tokens, index)
        if parsed is not None:
            amount, currency, consumed = parsed
            after = tokens[index + consumed :]
            before = tokens[:index]
            break
        index += 1

    if amount is None:
        raise QuickParseError("Не нашёл сумму в сообщении")

    exact, prefixes = build_index(categories or ())

    match_after = match_category(after, exact, prefixes) if after else None
    match_before = match_category(before, exact, prefixes) if before else None

    category: str | None = None
    if match_after:
        start, end, category = match_after
        comment_parts = before + after[:start] + after[end:]
    elif match_before:
        start, end, category = match_before
        comment_parts = before[:start] + before[end:] + after
    else:
        comment_parts = before + after

    comment = " ".join(part for part in comment_parts if part.strip()).strip()
    return ParsedExpense(
        amount=amount,
        currency=currency,
        category=category,
        comment=comment or None,
        raw=raw,
    )
