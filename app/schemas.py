"""Pydantic-схемы: валидация входных данных и формат ответов API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import settings


# --------------------------------------------------------------------------- #
# Пользователи
# --------------------------------------------------------------------------- #
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_id: int
    username: str | None = None
    full_name: str | None = None
    created_at: datetime | None = None

    @property
    def display_name(self) -> str:
        return self.full_name or self.username or f"id{self.telegram_id}"


class UserTotal(UserOut):
    total: float = 0.0
    count: int = 0
    share: float = 0.0


# --------------------------------------------------------------------------- #
# Категории
# --------------------------------------------------------------------------- #
class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    emoji: str | None = None
    synonyms: str | None = ""
    is_active: bool = True

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}".strip() if self.emoji else self.name


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    emoji: str | None = Field(default=None, max_length=16)
    synonyms: str | None = ""

    @model_validator(mode="after")
    def _strip(self) -> "CategoryCreate":
        self.name = self.name.strip()
        if self.emoji is not None:
            self.emoji = self.emoji.strip() or None
        if self.synonyms is not None:
            self.synonyms = self.synonyms.strip()
        return self


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    emoji: str | None = Field(default=None, max_length=16)
    synonyms: str | None = None
    is_active: bool | None = None


class CategoryTotal(BaseModel):
    category_id: int | None = None
    name: str
    emoji: str | None = None
    total: float = 0.0
    count: int = 0
    share: float = 0.0

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.name}".strip() if self.emoji else self.name


# --------------------------------------------------------------------------- #
# Расходы
# --------------------------------------------------------------------------- #
class ExpenseCreate(BaseModel):
    amount: float = Field(gt=0, le=10_000_000)
    category_id: int | None = None
    category_name: str | None = None
    user_id: int | None = None
    telegram_id: int | None = None
    comment: str | None = Field(default=None, max_length=500)
    currency: str | None = None
    spent_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "ExpenseCreate":
        if self.category_id is None and not (self.category_name or "").strip():
            raise ValueError("Нужно указать category_id или category_name")
        if self.user_id is None and self.telegram_id is None:
            raise ValueError("Нужно указать user_id или telegram_id")
        if self.comment is not None:
            self.comment = self.comment.strip() or None
        if self.category_name is not None:
            self.category_name = self.category_name.strip() or None
        if self.currency is not None:
            self.currency = self.currency.strip().upper() or None
        return self


class QuickExpenseIn(BaseModel):
    """Быстрый ввод строкой: '500 продукты хлеб и молоко'."""

    text: str = Field(min_length=1, max_length=500)
    user_id: int | None = None
    telegram_id: int | None = None
    category_id: int | None = None


class ExpenseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: float
    currency: str = settings.default_currency
    comment: str | None = None
    spent_at: datetime
    created_at: datetime | None = None
    category: CategoryOut | None = None
    user: UserOut | None = None


# --------------------------------------------------------------------------- #
# Статистика
# --------------------------------------------------------------------------- #
class DailyTotal(BaseModel):
    day: date
    total: float = 0.0
    count: int = 0


class MonthlyTotal(BaseModel):
    month: str
    total: float = 0.0
    count: int = 0


class SummaryOut(BaseModel):
    start: date
    end: date
    total: float = 0.0
    count: int = 0
    avg_per_day: float = 0.0
    days: int = 1


class PeriodComparison(BaseModel):
    current_total: float = 0.0
    previous_total: float = 0.0
    delta: float = 0.0
    delta_percent: float | None = None


# --------------------------------------------------------------------------- #
# Бюджеты
# --------------------------------------------------------------------------- #
class BudgetCreate(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    limit_amount: float = Field(ge=0)
    category_id: int | None = None


class BudgetProgress(BaseModel):
    budget_id: int | None = None
    month: str
    category_id: int | None = None
    category_name: str = "Всё вместе"
    emoji: str | None = None
    limit_amount: float = 0.0
    spent: float = 0.0
    remaining: float = 0.0
    percent: float = 0.0
    over: bool = False

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.category_name}".strip() if self.emoji else self.category_name
