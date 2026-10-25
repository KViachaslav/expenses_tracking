"""Импорт трат из CSV (колонки `date`, `amount`, `category`).

Используется для переноса данных из другого трекера: `import_csv.py` —
тонкая CLI-обёртка вокруг :func:`import_expenses_csv`.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category, Expense, User
from app.services.categories import create_category, list_categories, normalize_name
from app.services.expenses import add_expense, normalize_amount
from app.timeutils import to_datetime

REQUIRED_COLUMNS = ("date", "amount", "category")
# Дата в CSV без времени: ставим полдень, чтобы запись не «переезжала» между днями.
IMPORT_TIME = time(12, 0)

DEFAULT_FALLBACK_CATEGORY = "Прочее"
CATEGORY_MODES = ("map", "create")

# Правила «название из CSV -> категория приложения»: проверяются по порядку,
# совпадение — по подстроке в нормализованном названии (регистр не важен).
MERCHANT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Транспорт",
        ("whoosh", "yandexgo", "yandex go", "такси", "metro", "ecolines", "azs", "transportn"),
    ),
    ("ЖКХ", ("kommunalk", "жкх", "квартплат", "коммунал")),
    ("Здоровье", ("aptek", "аптек", "zdorov", "медицин")),
    ("Связь", ("belpochta", "vpn", "internet", "связь", "мобильн")),
    (
        "Развлечения",
        ("hokkey", "хоккей", "bowling", "fonbet", "spotify", "kinoteatr", "кинотеатр",
         "ermitazh", "эрмитаж", "dinamo", "mooon"),
    ),
    (
        "Кафе",
        ("kafe", "кафе", "kofe", "кофе", "kofeyn", "kava", "bar", "pab", "rest", "bufet",
         "kfc", "pizza", "пицц", "cushi", "sushi", "teremok", "tofu", "voron", "shumeli",
         "khachapuri", "aranchino", "cats republic", "semishagoff", "chayu", "french",
         "obed", "обед", "столов", "pekarn"),
    ),
    (
        "Продукты",
        ("galamart", "gipermarket", "universam", "magazin", "perek", "yagodka", "khleb",
         "yabloko", "24 tvoe", "materik", "delivio", "sladost", "produkt", "продукт",
         "supermarket", "tri ts"),
    ),
    (
        "Прочее",
        ("ozon", "wildberries", "elektronika", "электроника", "elektrosila", "5element",
         "optiks", "zooshop", "zoo", "mossmoda", "одежда", "hotel", "101hotels"),
    ),
)


@dataclass(frozen=True)
class CategoryMatch:
    """Результат сопоставления названия из CSV с категорией."""

    category: Category
    merchant: str | None = None  # исходное название, если сработало правило


@dataclass
class ImportReport:
    """Итоги импорта (для CLI и тестов)."""

    rows: int = 0
    imported: int = 0
    skipped: int = 0
    mapped: int = 0
    created_categories: list[str] = field(default_factory=list)
    by_category: dict[str, int] = field(default_factory=dict)
    total: float = 0.0
    first_date: date | None = None
    last_date: date | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def period(self) -> str:
        """Период импортированных трат в формате `дд.мм.гггг — дд.мм.гггг`."""
        if self.first_date is None or self.last_date is None:
            return "—"
        return f"{self.first_date:%d.%m.%Y} — {self.last_date:%d.%m.%Y}"


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    """Читает CSV (UTF-8 или CP1251) и возвращает непустые строки как словари.

    Пустые строки-разделители между днями игнорируются, названия колонок
    сравниваются без учёта регистра и пробелов.
    """
    raw = Path(path).read_bytes()
    text = ""
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Не удалось определить кодировку CSV (ожидались UTF-8 или CP1251)")

    reader = csv.DictReader(io.StringIO(text, newline=""))
    columns = {str(name).strip().lower(): name for name in (reader.fieldnames or [])}
    missing = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing:
        raise ValueError(f"В CSV нет колонок: {', '.join(missing)}")

    rows: list[dict[str, str]] = []
    for raw_row in reader:
        values = {key: (raw_row.get(source) or "").strip() for key, source in columns.items()}
        if not any(values.values()):
            continue
        rows.append(values)
    return rows


def import_expenses_csv(
    session: Session,
    path: str | Path,
    *,
    user: User,
    currency: str | None = None,
    use_synonyms: bool = True,
    category_mode: str = "map",
    fallback_category: str = DEFAULT_FALLBACK_CATEGORY,
    at_time: time = IMPORT_TIME,
    dry_run: bool = False,
) -> ImportReport:
    """Импортирует траты из CSV за пользователя `user`.

    * Категория ищется по названию, затем (если `use_synonyms`) по синонимам.
    * `category_mode="map"` — неизвестные названия (обычно имена магазинов)
      раскладываются по правилам :data:`MERCHANT_RULES`, а если правила нет —
      в `fallback_category`; исходное название сохраняется в комментарии.
      `category_mode="create"` — для каждого названия создаётся категория.
    * Повторный запуск не дублирует данные: строки, которые уже есть в БД
      (та же дата, категория и сумма у этого пользователя), пропускаются.
    * При `dry_run=True` все изменения откатываются, а отчёт возвращается.
    """
    if category_mode not in CATEGORY_MODES:
        raise ValueError(f"category_mode должен быть одним из {CATEGORY_MODES}")

    report = ImportReport()
    rows = read_csv_rows(path)
    report.rows = len(rows)

    existing = _existing_expenses(session, user.id)
    by_name = {
        normalize_name(category.name): category
        for category in list_categories(session, include_inactive=True)
    }
    by_keyword = _keyword_index(by_name.values(), use_synonyms=use_synonyms)
    resolved: dict[str, CategoryMatch] = {}

    for number, row in enumerate(rows, start=2):
        try:
            day = _parse_date(row.get("date"))
            amount = normalize_amount(row.get("amount") or "")
            if amount <= 0:
                raise ValueError("сумма должна быть больше нуля")
        except ValueError as exc:
            report.errors.append(f"строка {number}: {exc}")
            continue

        name = (row.get("category") or "").strip()
        if not name:
            report.errors.append(f"строка {number}: не указана категория")
            continue

        match = _resolve_category(
            session,
            name,
            report=report,
            resolved=resolved,
            by_name=by_name,
            by_keyword=by_keyword,
            use_synonyms=use_synonyms,
            category_mode=category_mode,
            fallback_category=fallback_category,
        )
        category = match.category

        moment = datetime.combine(day, at_time)
        key = (moment, category.id, round(amount, 2))
        if existing[key] > 0:
            existing[key] -= 1
            report.skipped += 1
            continue

        add_expense(
            session,
            user=user,
            category=category,
            amount=amount,
            comment=row.get("comment") or match.merchant,
            spent_at=moment,
            currency=currency,
        )
        report.imported += 1
        report.mapped += int(match.merchant is not None)
        report.by_category[category.name] = report.by_category.get(category.name, 0) + 1
        report.total = round(report.total + amount, 2)
        report.first_date = day if report.first_date is None else min(report.first_date, day)
        report.last_date = day if report.last_date is None else max(report.last_date, day)

    if dry_run:
        session.rollback()
    return report


# --------------------------------------------------------------------------- #
# Внутренние помощники
# --------------------------------------------------------------------------- #
def _existing_expenses(session: Session, user_id: int) -> Counter:
    """Счётчик (дата-время, категория, сумма) по тратам пользователя."""
    rows = session.execute(
        select(Expense.spent_at, Expense.category_id, Expense.amount).where(
            Expense.user_id == user_id
        )
    )
    return Counter((row[0], row[1], round(float(row[2]), 2)) for row in rows)


def _keyword_index(categories, *, use_synonyms: bool) -> dict[str, Category]:
    """Индекс «синоним -> категория» (только если включено сопоставление)."""
    if not use_synonyms:
        return {}
    index: dict[str, Category] = {}
    for category in categories:
        for keyword in category.keyword_list:
            index.setdefault(normalize_name(keyword), category)
    return index


def match_merchant(name: str) -> str | None:
    """Категория приложения для названия из CSV (по правилам MERCHANT_RULES)."""
    needle = normalize_name(name)
    for category_name, keywords in MERCHANT_RULES:
        if any(keyword in needle for keyword in keywords):
            return category_name
    return None


def _resolve_category(
    session: Session,
    name: str,
    *,
    report: ImportReport,
    resolved: dict[str, CategoryMatch],
    by_name: dict[str, Category],
    by_keyword: dict[str, Category],
    use_synonyms: bool,
    category_mode: str,
    fallback_category: str,
) -> CategoryMatch:
    """Сопоставляет название из CSV с категорией (или создаёт новую)."""
    key = normalize_name(name)
    if key in resolved:
        return resolved[key]

    category = by_name.get(key) or by_keyword.get(key)
    if category is not None:
        match = CategoryMatch(category)
    elif category_mode == "create":
        match = CategoryMatch(
            _create_category(
                session,
                name,
                report=report,
                by_name=by_name,
                by_keyword=by_keyword,
                use_synonyms=use_synonyms,
            )
        )
    else:
        target = match_merchant(name) or fallback_category
        category = by_name.get(normalize_name(target))
        if category is None:
            category = _create_category(
                session,
                target,
                report=report,
                by_name=by_name,
                by_keyword=by_keyword,
                use_synonyms=use_synonyms,
            )
        # Исходное название сохраняем в комментарии, чтобы не потерять детали.
        match = CategoryMatch(category, merchant=name)

    resolved[key] = match
    return match


def _create_category(
    session: Session,
    name: str,
    *,
    report: ImportReport,
    by_name: dict[str, Category],
    by_keyword: dict[str, Category],
    use_synonyms: bool,
) -> Category:
    """Создаёт категорию и обновляет индексы поиска."""
    category = create_category(session, name)
    by_name[normalize_name(category.name)] = category
    report.created_categories.append(category.name)
    if use_synonyms:
        for keyword in category.keyword_list:
            by_keyword.setdefault(normalize_name(keyword), category)
    return category



def _parse_date(value: str | None) -> date:
    """Разбирает дату из CSV (`YYYY-MM-DD` или `DD.MM.YYYY`)."""
    text = (value or "").strip()
    if not text:
        raise ValueError("не указана дата")
    try:
        parsed = to_datetime(text)
    except ValueError as exc:
        raise ValueError(f"некорректная дата {text!r}") from exc
    if parsed is None:
        raise ValueError("не указана дата")
    return parsed.date()
