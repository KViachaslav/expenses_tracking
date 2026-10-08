"""Тесты парсера быстрого ввода (`app.bot.parser`) — без БД."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.bot.parser import (
    QuickParseError,
    build_index,
    normalize_token,
    parse_amount,
    parse_amount_at,
    parse_amount_token,
    parse_quick_input,
    tokenize,
)
from app.services import categories as categories_service

KEYWORDS: tuple[tuple[str, str], ...] = (
    ("Продукты", "продукты"),
    ("Продукты", "еда"),
    ("Транспорт", "такси"),
    ("Связь", "мобильная"),
    ("Связь", "связь"),
)


def test_normalize_token_strips_punctuation() -> None:
    assert normalize_token("  Такси! ") == "такси"
    assert normalize_token("«Хлеб»") == "хлеб"


def test_tokenize_keeps_order() -> None:
    assert tokenize(" 500  продукты   хлеб ") == ["500", "продукты", "хлеб"]
    assert tokenize("") == []


def test_parse_amount_token_variants() -> None:
    assert parse_amount_token("500") == (500.0, None)
    assert parse_amount_token("1 234,56") == (1234.56, None)
    assert parse_amount_token("500р") == (500.0, "RUB")
    assert parse_amount_token("10$") == (10.0, "USD")
    assert parse_amount_token("хлеб") is None
    assert parse_amount_token("usd") is None


def test_parse_amount_from_text() -> None:
    assert parse_amount("1234.56 продуктов") == (1234.56, None)
    assert parse_amount("сумма 890") == (890.0, None)
    with pytest.raises(QuickParseError):
        parse_amount("привет как дела")


def test_parse_amount_grouped_digits() -> None:
    """Пробел как разделитель разрядов («1 500», «7 654,32 руб»)."""
    assert parse_amount("1 500") == (1500.0, None)
    assert parse_amount("7 654,32 руб") == (7654.32, "RUB")
    assert parse_amount("бюджет 12 000,50") == (12000.5, None)
    assert parse_amount("1 500 000 продуктов") == (1500000.0, None)
    assert parse_amount_at(["1", "500"], 0) == (1500.0, None, 2)
    assert parse_amount_at(["хлеб"], 0) is None


def test_build_index_exact_and_prefix() -> None:
    exact, prefixes = build_index(KEYWORDS)
    assert exact["такси"] == "Транспорт"
    assert prefixes["продукт"] == "Продукты"


def test_quick_input_amount_category_comment() -> None:
    parsed = parse_quick_input("500 продукты хлеб и молоко", KEYWORDS)
    assert parsed.amount == 500.0
    assert parsed.category == "Продукты"
    assert parsed.comment == "хлеб и молоко"
    assert parsed.raw == "500 продукты хлеб и молоко"
    assert parsed.currency is None


def test_quick_input_category_before_amount() -> None:
    parsed = parse_quick_input("такси 300 домой", KEYWORDS)
    assert parsed.amount == 300.0
    assert parsed.category == "Транспорт"
    assert parsed.comment == "домой"


def test_quick_input_thousands_with_space() -> None:
    parsed = parse_quick_input("1 500 такси", KEYWORDS)
    assert parsed.amount == 1500.0
    assert parsed.category == "Транспорт"
    assert parsed.comment is None


def test_quick_input_grouped_digits_with_currency() -> None:
    parsed = parse_quick_input("7 654,32 руб еда", KEYWORDS)
    assert (parsed.amount, parsed.currency) == (7654.32, "RUB")
    assert parsed.category == "Продукты"
    assert parsed.comment is None


def test_quick_input_decimal_comma() -> None:
    parsed = parse_quick_input("1234,50 еда", KEYWORDS)
    assert parsed.amount == 1234.5
    assert parsed.category == "Продукты"


def test_quick_input_currency_suffix() -> None:
    parsed = parse_quick_input("500р такси", KEYWORDS)
    assert (parsed.amount, parsed.currency, parsed.category) == (500.0, "RUB", "Транспорт")


def test_quick_input_unknown_category_goes_to_comment() -> None:
    parsed = parse_quick_input("45.25 молоко", ())
    assert parsed.amount == 45.25
    assert parsed.category is None
    assert parsed.comment == "молоко"


def test_quick_input_multiword_category() -> None:
    parsed = parse_quick_input("25 мобильная связь", KEYWORDS)
    assert parsed.amount == 25.0
    assert parsed.category == "Связь"
    assert parsed.comment is None


def test_quick_input_errors() -> None:
    with pytest.raises(QuickParseError):
        parse_quick_input("")
    with pytest.raises(QuickParseError):
        parse_quick_input("привет")
    with pytest.raises(QuickParseError):
        parse_quick_input("продукты хлеб", KEYWORDS)


def test_quick_input_with_categories_from_db(session: Session) -> None:
    """Интеграция: ключевые слова берутся из справочника категорий."""
    keywords = categories_service.parser_keywords(session)
    parsed = parse_quick_input("500 продуктовый хлеб", keywords)
    assert parsed.amount == 500.0
    assert parsed.category == "Продукты"
    assert parsed.comment == "хлеб"

    parsed = parse_quick_input("30 кино билеты", keywords)
    assert parsed.category == "Развлечения"
    assert parsed.comment == "билеты"
