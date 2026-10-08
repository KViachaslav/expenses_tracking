"""SQLAlchemy-модели: пользователи, категории, расходы, бюджеты."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.database import Base
from app.timeutils import local_now


class User(Base):
    """Член семьи (пользователь Telegram)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=local_now)

    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        return self.full_name or self.username or f"id{self.telegram_id}"

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"<User id={self.id} tg={self.telegram_id} name={self.display_name!r}>"


class Category(Base):
    """Категория расходов со словами-синонимами для быстрого ввода."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(16))
    synonyms: Mapped[str | None] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=local_now)

    expenses: Mapped[list["Expense"]] = relationship(back_populates="category")

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}".strip() if self.emoji else self.name

    @property
    def keyword_list(self) -> list[str]:
        """Название + синонимы (нормализованные, без пустых)."""
        raw: list[str] = [self.name, *(self.synonyms or "").replace(";", ",").split(",")]
        result: list[str] = []
        for item in raw:
            keyword = item.strip().lower()
            if keyword and keyword not in result:
                result.append(keyword)
        return result

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"<Category id={self.id} name={self.name!r}>"


class Expense(Base):
    """Одна трата."""

    __tablename__ = "expenses"
    __table_args__ = (
        Index("idx_expenses_spent_at", "spent_at"),
        Index("idx_expenses_category", "category_id"),
        Index("idx_expenses_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default=settings.default_currency)
    comment: Mapped[str | None] = mapped_column(Text)
    spent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=local_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=local_now)

    user: Mapped["User"] = relationship(back_populates="expenses")
    category: Mapped["Category"] = relationship(back_populates="expenses")

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"<Expense id={self.id} amount={self.amount} category_id={self.category_id}>"


class Budget(Base):
    """Лимит расходов на месяц (category_id = None -> общий бюджет)."""

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("category_id", "month", name="uq_budgets_category_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="CASCADE")
    )
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    limit_amount: Mapped[float] = mapped_column(Float, nullable=False)

    category: Mapped["Category | None"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - отладка
        return f"<Budget id={self.id} month={self.month} limit={self.limit_amount}>"
