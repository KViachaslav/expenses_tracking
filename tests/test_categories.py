"""Тесты справочника категорий (`app.services.categories`).

Отдельное внимание — сравнению имён без учёта регистра: SQLite `lower()`
не умеет кириллицу, поэтому нормализация делается в Python (`casefold`).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Expense
from app.services import categories as cats
from app.services import expenses as expenses_service


def test_default_categories_are_seeded(session: Session) -> None:
    assert len(cats.list_categories(session)) == len(cats.DEFAULT_CATEGORIES)
    names = [item.name for item in cats.list_categories(session)]
    assert names[:3] == ["Продукты", "Транспорт", "ЖКХ"]


def test_seed_is_idempotent(session: Session) -> None:
    assert cats.seed_default_categories(session) == 0
    assert len(cats.list_categories(session)) == len(cats.DEFAULT_CATEGORIES)


def test_normalize_name_folds_cyrillic_case() -> None:
    assert cats.normalize_name("  ПРОДУКТЫ ") == "продукты"
    assert cats.normalize_name("ЖКХ") == cats.normalize_name("жкх")
    assert cats.normalize_name("Кафе\n") == "кафе"
    assert cats.normalize_name(None) == ""


def test_find_by_name_ignores_case_and_spaces(session: Session) -> None:
    assert cats.find_by_name(session, "  продукты ").name == "Продукты"
    assert cats.find_by_name(session, "ЖКХ").name == "ЖКХ"
    assert cats.find_by_name(session, "нет такой") is None
    assert cats.find_by_name(session, "  ") is None


def test_find_by_name_exclude_id(session: Session) -> None:
    products = cats.find_by_name(session, "Продукты")
    assert cats.find_by_name(session, "Продукты", exclude_id=products.id) is None


def test_create_category_trims_and_rejects_duplicates(session: Session) -> None:
    created = cats.create_category(session, "  Дача ", "🏡", " огород ")
    assert created.name == "Дача"
    assert created.emoji == "🏡"
    assert created.synonyms == "огород"
    assert created.is_active is True

    with pytest.raises(ValueError):
        cats.create_category(session, "дача")
    with pytest.raises(ValueError):
        cats.create_category(session, "ПРОДУКТЫ")
    with pytest.raises(ValueError):
        cats.create_category(session, "   ")


def test_update_category_checks_duplicates(session: Session) -> None:
    dacha = cats.create_category(session, "Дача")
    updated = cats.update_category(session, dacha, name="Загород", emoji="🌳", is_active=False)
    assert (updated.name, updated.emoji, updated.is_active) == ("Загород", "🌳", False)

    with pytest.raises(ValueError):
        cats.update_category(session, dacha, name="продукты")
    with pytest.raises(ValueError):
        cats.update_category(session, dacha, name="   ")


def test_delete_category_removes_unused(session: Session) -> None:
    dacha = cats.create_category(session, "Дача")
    session.flush()
    assert cats.delete_category(session, dacha) is True
    assert cats.find_by_name(session, "Дача") is None


def test_delete_category_deactivates_used(
    session: Session, add_expense, user, categories
) -> None:
    add_expense(user, categories["Продукты"], 100.0)
    assert cats.delete_category(session, categories["Продукты"]) is False
    assert cats.find_by_name(session, "Продукты").is_active is False
    active = [item.name for item in cats.list_categories(session)]
    assert "Продукты" not in active
    assert len(active) == len(cats.DEFAULT_CATEGORIES) - 1


def test_category_usage_counts_amounts(session: Session, add_expense, user, categories) -> None:
    add_expense(user, categories["Продукты"], 100.5)
    add_expense(user, categories["Продукты"], 50.0)
    add_expense(user, categories["Транспорт"], 25.0)
    usage = cats.category_usage(session)
    assert usage[categories["Продукты"].id] == (150.5, 2)
    assert usage[categories["Транспорт"].id] == (25.0, 1)
    assert categories["ЖКХ"].id not in usage


def test_keywords_for_sorted_by_length(session: Session) -> None:
    keywords = cats.keywords_for(cats.list_categories(session))
    lengths = [len(keyword) for _, keyword in keywords]
    assert lengths == sorted(lengths, reverse=True)
    assert ("Связь", "мобильная") in keywords


def test_ordered_by_usage_puts_active_first(session: Session, add_expense, user, categories) -> None:
    add_expense(user, categories["Транспорт"], 10.0)
    dacha = cats.create_category(session, "Дача")
    cats.update_category(session, dacha, is_active=False)
    session.commit()

    ordered = cats.ordered_by_usage(session, include_inactive=True)
    assert ordered[0].name == "Транспорт"
    assert ordered[-1].name == "Дача"


def test_category_names_includes_inactive(session: Session) -> None:
    dacha = cats.create_category(session, "Дача")
    cats.update_category(session, dacha, is_active=False)
    assert "Дача" in cats.category_names(session)
    assert "Дача" not in [item.name for item in cats.list_categories(session)]


def test_find_category_by_id_and_synonym(session: Session) -> None:
    products = cats.find_by_name(session, "Продукты")
    assert cats.find_category(session, str(products.id)).name == "Продукты"
    assert cats.find_category(session, "еда").name == "Продукты"
    assert cats.find_category(session, "мобильная").name == "Связь"
    assert cats.find_category(session, "") is None
    assert cats.find_category(session, "абракадабра") is None


def test_add_expense_rejects_non_positive(session: Session, user, categories) -> None:
    with pytest.raises(ValueError):
        expenses_service.add_expense(session, user=user, category=categories["Кафе"], amount=0)
    assert list(session.scalars(select(Expense))) == []
