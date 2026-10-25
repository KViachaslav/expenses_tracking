"""Импорт трат из CSV в базу приложения: `python import_csv.py FILE.csv`.

Формат файла: колонки `date` (`YYYY-MM-DD` или `DD.MM.YYYY`), `amount`,
`category`. Владелец трат — первый пользователь БД либо явно указанный
(`--user-id` / `--telegram-id`). Повторный запуск не создаёт дубликатов.

Названия магазинов из CSV по умолчанию раскладываются по категориям
приложения (`MERCHANT_RULES`), исходное название попадает в комментарий.
Флаг `--keep-categories` создаёт категории ровно как в файле.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, init_db
from app.formatting import format_money
from app.models import User
from app.services.expenses import get_user, get_user_by_telegram_id, list_users
from app.services.importer import DEFAULT_FALLBACK_CATEGORY, import_expenses_csv

PREVIEW_CATEGORIES = 15


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Импорт трат из CSV (date,amount,category) в базу приложения.",
    )
    parser.add_argument("csv_path", help="путь к CSV-файлу")
    parser.add_argument("--user-id", type=int, help="id владельца трат")
    parser.add_argument("--telegram-id", type=int, help="telegram_id владельца трат")
    parser.add_argument(
        "--currency",
        help=f"валюта импортируемых трат (по умолчанию {settings.default_currency})",
    )
    parser.add_argument(
        "--keep-categories",
        action="store_true",
        help="создавать категории ровно как в CSV вместо раскладки по правилам",
    )
    parser.add_argument(
        "--fallback-category",
        default=DEFAULT_FALLBACK_CATEGORY,
        help=f"категория для названий без правила (по умолчанию {DEFAULT_FALLBACK_CATEGORY})",
    )
    parser.add_argument(
        "--no-synonyms",
        action="store_true",
        help="не сопоставлять категории по синонимам (только по названию)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="только посчитать строки, ничего не записывать",
    )
    return parser


def resolve_user(session: Session, *, user_id: int | None, telegram_id: int | None) -> User:
    """Находит владельца импортируемых трат."""
    if telegram_id is not None:
        user = get_user_by_telegram_id(session, telegram_id)
        if user is None:
            raise SystemExit(f"Пользователь с telegram_id={telegram_id} не найден в БД")
        return user
    if user_id is not None:
        user = get_user(session, user_id)
        if user is None:
            raise SystemExit(f"Пользователь с id={user_id} не найден в БД")
        return user

    users = list_users(session)
    if not users:
        raise SystemExit(
            "В БД нет пользователей: отправьте боту /start, затем укажите --user-id или --telegram-id"
        )
    return users[0]


def _categories_preview(names: list[str]) -> str:
    if len(names) <= PREVIEW_CATEGORIES:
        return ", ".join(names)
    shown = ", ".join(names[:PREVIEW_CATEGORIES])
    return f"{shown} и ещё {len(names) - PREVIEW_CATEGORIES}"


def main(argv: list[str] | None = None) -> int:
    # Консоль Windows часто в cp1251 и падает на кириллице — печатаем в UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.user_id is not None and args.telegram_id is not None:
        parser.error("укажите что-то одно: --user-id или --telegram-id")

    init_db()
    with SessionLocal() as session:
        user = resolve_user(session, user_id=args.user_id, telegram_id=args.telegram_id)
        owner = f"id={user.id}, telegram_id={user.telegram_id}, {user.display_name}"

        report = import_expenses_csv(
            session,
            args.csv_path,
            user=user,
            currency=args.currency,
            use_synonyms=not args.no_synonyms,
            category_mode="create" if args.keep_categories else "map",
            fallback_category=args.fallback_category,
            dry_run=args.dry_run,
        )
        if not args.dry_run:
            session.commit()

    currency = args.currency or settings.default_currency
    prefix = "DRY-RUN, изменения откачены: " if args.dry_run else ""
    print(f"{prefix}{args.csv_path}")
    print(f"  строк в CSV:              {report.rows}")
    print(f"  добавлено трат:           {report.imported} на {format_money(report.total, currency)}")
    print(f"  пропущено (уже есть в БД): {report.skipped}")
    print(f"  сопоставлено по правилам: {report.mapped}")
    print(f"  новых категорий:          {len(report.created_categories)}")
    if report.created_categories:
        print(f"    {_categories_preview(report.created_categories)}")
    if report.by_category:
        print("  по категориям:")
        for name, count in sorted(report.by_category.items(), key=lambda item: -item[1]):
            print(f"    {count:5d}  {name}")
    print(f"  период:                   {report.period}")
    print(f"  владелец:                 {owner}")
    if report.errors:
        print(f"  ошибок:                   {len(report.errors)}")
        for error in report.errors:
            print(f"    - {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
