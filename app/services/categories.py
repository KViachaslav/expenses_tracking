"""Справочник категорий: категории по умолчанию, CRUD, поиск по синонимам."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Category, Expense

# (название, эмодзи, синонимы через запятую)
DEFAULT_CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("Продукты", "🛒", "продукты,продукт,еда,магазин,супермаркет,продуктовый"),
    ("Транспорт", "🚌", "транспорт,бензин,такси,автобус,метро,проезд,заправка"),
    ("ЖКХ", "🏠", "жкх,коммуналка,квартплата,коммунальные,вода,свет,газ"),
    ("Кафе", "🍔", "кафе,ресторан,кофе,фастфуд,обед,столовая,пицца"),
    ("Развлечения", "🎬", "развлечения,кино,игры,игра,концерт,подписка,досуг"),
    ("Здоровье", "💊", "здоровье,аптека,врач,лекарства,медицина,анализы"),
    ("Связь", "📱", "связь,интернет,мобильная,телефон,мобильный,тариф"),
    ("Прочее", "📦", "прочее,разное,другое,прочие,проч"),
)


def normalize_name(name: str | None) -> str:
    """Ключ для сравнения названий: без учёта регистра и лишних пробелов.

    Сравнение делаем в Python: SQLite `lower()` не умеет кириллицу,
    поэтому `func.lower(name)` для русских названий бесполезен.
    """
    return " ".join((name or "").split()).casefold()


def find_by_name(session: Session, name: str, *, exclude_id: int | None = None) -> Category | None:
    """Ищет категорию по названию без учёта регистра."""
    needle = normalize_name(name)
    if not needle:
        return None
    categories = session.scalars(select(Category).order_by(Category.id))
    for category in categories:
        if exclude_id is not None and category.id == exclude_id:
            continue
        if normalize_name(category.name) == needle:
            return category
    return None


def seed_default_categories(session: Session) -> int:
    """Добавляет категории по умолчанию. Возвращает число созданных."""
    created = 0
    for name, emoji, synonyms in DEFAULT_CATEGORIES:
        if find_by_name(session, name) is not None:
            continue
        session.add(Category(name=name, emoji=emoji, synonyms=synonyms, is_active=True))
        session.flush()
        created += 1
    session.flush()
    return created


def list_categories(session: Session, *, include_inactive: bool = False) -> list[Category]:
    """Активные категории (или все) в порядке добавления."""
    query = select(Category).order_by(Category.id)
    if not include_inactive:
        query = query.where(Category.is_active.is_(True))
    return list(session.scalars(query))


def get_category(session: Session, category_id: int | None) -> Category | None:
    if category_id is None:
        return None
    return session.get(Category, category_id)


def find_category(session: Session, query: str | None) -> Category | None:
    """Поиск категории по id/названию/синониму (регистр не важен)."""
    if not query or not str(query).strip():
        return None
    text = str(query).strip()
    if text.isdigit():
        found = get_category(session, int(text))
        if found:
            return found

    needle = normalize_name(text)
    categories = list(list_categories(session, include_inactive=True))

    for category in categories:
        if normalize_name(category.name) == needle:
            return category
    for category in categories:
        if needle in [normalize_name(keyword) for keyword in category.keyword_list]:
            return category
    for category in categories:
        if needle in normalize_name(category.name):
            return category
    for category in categories:
        for keyword in category.keyword_list:
            if len(keyword) >= 3 and (needle in keyword or keyword in needle):
                return category
    return None


def create_category(
    session: Session,
    name: str,
    emoji: str | None = None,
    synonyms: str | None = "",
) -> Category:
    """Создаёт категорию. Бросает ValueError, если имя занято."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Название категории не может быть пустым")
    if find_by_name(session, clean_name) is not None:
        raise ValueError(f"Категория «{clean_name}» уже существует")
    category = Category(
        name=clean_name,
        emoji=(emoji or "").strip() or None,
        synonyms=(synonyms or "").strip(),
        is_active=True,
    )
    session.add(category)
    session.flush()
    return category


def update_category(
    session: Session,
    category: Category,
    *,
    name: str | None = None,
    emoji: str | None = None,
    synonyms: str | None = None,
    is_active: bool | None = None,
) -> Category:
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Название категории не может быть пустым")
        duplicate = find_by_name(session, clean_name, exclude_id=category.id)
        if duplicate is not None:
            raise ValueError(f"Категория «{clean_name}» уже существует")
        category.name = clean_name
    if emoji is not None:
        category.emoji = emoji.strip() or None
    if synonyms is not None:
        category.synonyms = synonyms.strip()
    if is_active is not None:
        category.is_active = is_active
    session.flush()
    return category


def delete_category(session: Session, category: Category) -> bool:
    """Удаляет категорию. Если по ней есть траты — деактивирует.

    Возвращает True, если запись удалена, и False, если только отключена.
    """
    used = session.scalar(select(func.count(Expense.id)).where(Expense.category_id == category.id))
    if used:
        category.is_active = False
        session.flush()
        return False
    session.delete(category)
    session.flush()
    return True


def category_usage(session: Session) -> dict[int, tuple[float, int]]:
    """{category_id: (сумма, количество)} за всё время — для страницы категорий."""
    rows = session.execute(
        select(
            Expense.category_id,
            func.coalesce(func.sum(Expense.amount), 0.0),
            func.count(Expense.id),
        ).group_by(Expense.category_id)
    ).all()
    return {int(row[0]): (float(row[1]), int(row[2])) for row in rows}


def keywords_for(categories: Iterable[Category]) -> list[tuple[str, str]]:
    """Пары (название категории, ключевое слово) для парсера быстрого ввода.

    Сортировка по убыванию длины ключа — чтобы «мобильная связь» матчилась
    раньше, чем «связь».
    """
    pairs: list[tuple[str, str]] = []
    for category in categories:
        for keyword in category.keyword_list:
            pairs.append((category.name, keyword))
    pairs.sort(key=lambda item: len(item[1]), reverse=True)
    return pairs


def parser_keywords(session: Session) -> list[tuple[str, str]]:
    """Слова для парсера по активным категориям из БД."""
    return keywords_for(list_categories(session))


def ordered_by_usage(session: Session, *, include_inactive: bool = False) -> list[Category]:
    """Категории: активные сначала, затем по частоте использования."""
    usage = category_usage(session)
    categories = list_categories(session, include_inactive=include_inactive)
    return sorted(
        categories,
        key=lambda cat: (
            0 if cat.is_active else 1,
            -usage.get(cat.id, (0.0, 0))[1],
            cat.name.lower(),
        ),
    )


def category_names(session: Session) -> Sequence[str]:
    return [category.name for category in list_categories(session, include_inactive=True)]
