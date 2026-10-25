"""Тесты импорта трат из CSV (`app.services.importer`)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Expense
from app.services import importer
from app.services.categories import find_by_name, list_categories


def write_csv(path: Path, rows: list[list[str]], *, encoding: str = "utf-8") -> Path:
    """Пишет CSV с пустыми строками-разделителями, как в исходной выгрузке."""
    with path.open("w", encoding=encoding, newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "amount", "category"])
        for row in rows:
            writer.writerow(row)
            writer.writerow([])
    return path


def expense_count(session: Session) -> int:
    return session.scalar(select(func.count(Expense.id)))


def test_import_maps_merchants_to_app_categories(
    session: Session, user, categories, tmp_path: Path
) -> None:
    path = write_csv(
        tmp_path / "expenses.csv",
        [
            ["2026-10-07", "1.15", "Транспорт"],
            ["2026-10-08", "35.16", "OZON"],
            ["2026-10-09", "61.44", "Продукты"],
            ["2026-10-09", "12.40", "Обед"],
            ["2026-10-10", "7.00", "НЕИЗВЕСТНЫЙ МАГАЗИН"],
        ],
    )

    report = importer.import_expenses_csv(session, path, user=user)
    session.commit()

    assert report.rows == 5
    assert report.imported == 5
    assert report.skipped == 0
    assert report.errors == []
    assert report.total == 117.15
    assert report.mapped == 2  # OZON и магазин без правила
    assert report.created_categories == []
    assert report.by_category == {"Транспорт": 1, "Прочее": 2, "Продукты": 1, "Кафе": 1}
    assert report.period == "07.10.2026 — 10.10.2026"
    assert expense_count(session) == 5

    # «Обед» — синоним категории «Кафе», отдельная категория не создаётся.
    cafe = find_by_name(session, "Кафе")
    lunch = session.scalar(select(Expense).where(Expense.amount == 12.4))
    assert lunch.category_id == cafe.id
    assert lunch.spent_at == datetime(2026, 10, 9, 12, 0)
    assert lunch.currency == "BYN"
    assert lunch.comment is None

    # Мерчант без правила уходит в «Прочее», а название остаётся в комментарии.
    ozon = session.scalar(select(Expense).where(Expense.amount == 35.16))
    assert ozon.category_id == categories["Прочее"].id
    assert ozon.comment == "OZON"


def test_import_create_mode_keeps_csv_names(
    session: Session, user, tmp_path: Path
) -> None:
    path = write_csv(tmp_path / "expenses.csv", [["2026-10-08", "35.16", "OZON"]])

    report = importer.import_expenses_csv(session, path, user=user, category_mode="create")
    session.commit()

    assert report.created_categories == ["OZON"]
    assert report.mapped == 0
    assert report.by_category == {"OZON": 1}
    expense = session.scalar(select(Expense))
    assert expense.category.name == "OZON"
    assert expense.comment is None


def test_import_rejects_unknown_category_mode(session: Session, user, tmp_path: Path) -> None:
    path = write_csv(tmp_path / "expenses.csv", [["2026-10-08", "1.00", "Продукты"]])

    with pytest.raises(ValueError):
        importer.import_expenses_csv(session, path, user=user, category_mode="unknown")



def test_import_is_idempotent(session: Session, user, tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "expenses.csv",
        [
            ["2026-10-07", "1.15", "Транспорт"],
            ["2026-10-07", "1.15", "Транспорт"],
        ],
    )

    first = importer.import_expenses_csv(session, path, user=user)
    session.commit()
    assert first.imported == 2

    second = importer.import_expenses_csv(session, path, user=user)
    session.commit()
    assert second.imported == 0
    assert second.skipped == 2
    assert expense_count(session) == 2


def test_dry_run_changes_nothing(session: Session, user, tmp_path: Path) -> None:
    path = write_csv(tmp_path / "expenses.csv", [["2026-10-07", "5", "Новая категория"]])
    categories_before = len(list_categories(session, include_inactive=True))

    report = importer.import_expenses_csv(
        session, path, user=user, category_mode="create", dry_run=True
    )

    assert report.imported == 1
    assert report.created_categories == ["Новая категория"]
    assert expense_count(session) == 0
    assert len(list_categories(session, include_inactive=True)) == categories_before


def test_import_reports_bad_rows(session: Session, user, tmp_path: Path) -> None:
    path = write_csv(
        tmp_path / "expenses.csv",
        [
            ["31.13.2026", "10", "Транспорт"],
            ["2026-01-01", "abc", "Транспорт"],
            ["2026-01-01", "5", ""],
            ["2026-01-01", "0", "Транспорт"],
        ],
    )

    report = importer.import_expenses_csv(session, path, user=user)

    assert report.rows == 4
    assert report.imported == 0
    assert len(report.errors) == 4
    assert expense_count(session) == 0


def test_import_supports_cp1251_and_custom_currency(
    session: Session, user, tmp_path: Path
) -> None:
    path = write_csv(
        tmp_path / "cp1251.csv",
        [["01.09.2026", "3,50", "Продукты"]],
        encoding="cp1251",
    )

    report = importer.import_expenses_csv(session, path, user=user, currency="usd")
    session.commit()

    assert report.imported == 1
    assert report.total == 3.5
    expense = session.scalar(select(Expense))
    assert expense.currency == "USD"
    assert expense.spent_at == datetime(2026, 9, 1, 12, 0)


def test_import_without_synonyms_does_not_match_synonyms(
    session: Session, user, tmp_path: Path
) -> None:
    path = write_csv(
        tmp_path / "expenses.csv",
        [["2026-10-09", "12.4", "Обед"], ["2026-10-09", "5", "coffee"]],
    )

    report = importer.import_expenses_csv(
        session, path, user=user, use_synonyms=False, category_mode="create"
    )
    session.commit()

    assert report.created_categories == ["Обед", "coffee"]
    assert report.mapped == 0
    assert find_by_name(session, "Обед") is not None
    assert find_by_name(session, "Кафе").expenses == []


def test_read_csv_requires_columns(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("дата,сумма\n2026-01-01,5\n", encoding="utf-8")

    with pytest.raises(ValueError):
        importer.read_csv_rows(path)
