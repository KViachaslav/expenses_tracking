"""Быстрая проверка бота: импорт модулей, компиляция, разбор строки, рендер отчёта."""

from __future__ import annotations

import compileall
import pathlib
import sys
import traceback

ROOT = pathlib.Path(__file__).resolve().parent

# Консоль Windows часто в cp1251 и падает на эмодзи — печатаем в UTF-8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


log_lines: list[str] = []


def step(name: str, func) -> None:
    try:
        result = func()
        log_lines.append(f"[OK] {name}: {result}")
    except Exception:
        log_lines.append(f"[FAIL] {name}:\n{traceback.format_exc()}")


def imports() -> str:
    import app.bot.handlers  # noqa: F401
    import app.bot.keyboards  # noqa: F401
    import app.bot.main  # noqa: F401
    import app.bot.middlewares  # noqa: F401
    import app.bot.parser  # noqa: F401

    return "бот импортируется"


def dispatcher_setup() -> str:
    from app.bot.main import create_dispatcher

    dp = create_dispatcher()
    return f"хендлеров: {sum(len(r.message.handlers) + len(r.callback_query.handlers) for r in dp.sub_routers)}"


def parser_check() -> str:
    from app.bot.parser import parse_quick_input

    pairs = [("Продукты", "продукты"), ("Продукты", "еда"), ("Транспорт", "такси")]
    cases = {
        "500 продукты хлеб и молоко": (500.0, "Продукты", "хлеб и молоко"),
        "1 500 такси домой": (1500.0, "Транспорт", "домой"),
        "300,50 еда обед": (300.5, "Продукты", "обед"),
    }
    report: list[str] = []
    for text, expected in cases.items():
        got = parse_quick_input(text, pairs)
        assert (got.amount, got.category, got.comment) == expected, (text, got)
        report.append(f"{text!r} -> {got.amount} / {got.category} / {got.comment!r}")
    return "; ".join(report)


def db_check() -> str:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import Base, init_db
    from app.services import stats
    from app.services.categories import list_categories, parser_keywords
    from app.services.expenses import add_expense, ensure_user
    from app.timeutils import month_bounds

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    init_db(engine_=engine, session_factory=factory, seed=True)

    with factory() as session:
        user = ensure_user(session, 1, username="tester", full_name="Тест Тестов")
        categories = list_categories(session)
        assert len(categories) == 8, len(categories)
        assert parser_keywords(session)
        add_expense(session, user=user, category=categories[0], amount=1500, comment="проверка")
        session.commit()
        summary = stats.summary(session, *month_bounds())
        totals = stats.category_totals(session, *month_bounds())
        assert summary.total == 1500, summary
        assert totals and totals[0].title
    return f"категорий: {len(categories)}, итог месяца: {summary.total}, топ: {totals[0].title}"


def main() -> int:
    step("compileall", lambda: compileall.compile_dir(ROOT / "app", quiet=1) or "все файлы скомпилированы")
    step("import", imports)
    step("dispatcher", dispatcher_setup)
    step("parser", parser_check)
    step("db+stats", db_check)

    text = "\n".join(log_lines)
    (ROOT / "validate_bot.log").write_text(text, encoding="utf-8")
    print(text)
    return 1 if "[FAIL]" in text else 0


if __name__ == "__main__":
    sys.exit(main())
