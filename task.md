# 📋 гибридное приложение учёта трат на Raspberry Pi

## 🎯 Цель

Разработать и развернуть на Raspberry Pi **гибридное приложение** для отслеживания домашних расходов:

- **Telegram-бот** (aiogram) — ввод трат членами семьи
- **Веб-интерфейс** (FastAPI + Jinja2 + Chart.js) — просмотр статистики и графиков из локальной сети
- **SQLite** — единая база данных
- **systemd** — автозапуск обоих сервисов после перезагрузки

---

## 🖥️ Среда развёртывания

| Параметр | Значение |
|----------|----------|
| Устройство | Raspberry Pi (3/4/5), Raspberry Pi OS / Ubuntu Server |
| Подключение | SSH `slava@<IP_или_хост>` (пароль kachan) |
| Порт веб-приложения | `8080` |
| Доступ к сайту | Только из локальной сети, **без авторизации** |
| Автообновление данных | **Не требуется** (перезагрузка страницы вручную) |

---

## 🛠️ Стек технологий

| Слой | Технология |
|------|-----------|
| Язык | **Python 3.11+** |
| Telegram-бот | **aiogram** (v3) |
| Backend / веб | **FastAPI + uvicorn** |
| Шаблоны | **Jinja2** |
| Графики | **Chart.js** (CDN или локально) |
| БД | **SQLite** |
| ORM | **SQLAlchemy** + Alembic (миграции) |
| Процесс-менеджер | **systemd** |

---

## 📊 Модель данных (SQLite)

```sql
-- Пользователи (члены семьи)
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    full_name TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Категории расходов
CREATE TABLE categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    emoji TEXT,
    is_active BOOLEAN DEFAULT 1
);

-- Расходы
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    category_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    currency TEXT DEFAULT 'BYN',
    comment TEXT,
    spent_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(category_id) REFERENCES categories(id)
);

-- Бюджеты (опционально)
CREATE TABLE budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER,
    month TEXT NOT NULL,             -- '2025-01'
    limit_amount REAL NOT NULL,
    FOREIGN KEY(category_id) REFERENCES categories(id)
);

CREATE INDEX idx_expenses_spent_at ON expenses(spent_at);
CREATE INDEX idx_expenses_category ON expenses(category_id);
```

---

## 🤖 Функционал Telegram-бота (aiogram)

### Команды

| Команда | Действие |
|---------|----------|
| `/start` | Регистрация пользователя, краткая инструкция |
| `/add` | Интерактивное добавление расхода (FSM: сумма → категория → комментарий) |
| `/today` | Сумма расходов за сегодня |
| `/month` | Отчёт за текущий месяц |
| `/stats` | Топ категорий за месяц |
| `/categories` | Список категорий |
| `/addcat <название> <эмодзи>` | Добавить категорию (только админ) |
| `/cancel` | Отмена текущего действия |
| `/help` | Справка |

### Быстрый ввод одной строкой

Поддержать формат:
```
500 продукты хлеб и молоко
```
→ распарсить сумму, категорию (по названию или синониму), комментарий → записать в БД.

---

## 🌐 Веб-интерфейс (FastAPI + Jinja2)

### Страницы

1. **Dashboard** (`/`)
   - Карточки: сумма за сегодня, за месяц, средний расход в день, остаток бюджета
   - 📈 Линейный график — динамика за 30 дней
   - 🥧 Круговая диаграмма (doughnut) — доли категорий за месяц
   - 🏆 Горизонтальный бар — топ-5 категорий
   - 🎯 Прогресс-бары бюджетов по категориям
   - 🧾 Таблица последних 8–10 трат

2. **Отчёты** (`/reports`)
   - Фильтры по дате (от/до), категории, пользователю
   - Таблица с итогами
   - Экспорт в CSV

3. **Категории** (`/categories`)
   - Просмотр и управление справочником

4. **Пользователи** (`/users`)
   - Кто сколько тратит за период

### Требования

- Адаптивная вёрстка (работает с телефона в LAN)
- **Без авторизации**
- **Без автообновления** (данные обновляются при перезагрузке страницы)
- Chart.js подключается через CDN (или локально из `static/`, если нет интернета)

---

## 📁 Структура проекта

```
expense-tracker/
├── app/
│   ├── __init__.py
│   ├── config.py              # чтение .env
│   ├── database.py            # engine, SessionLocal, Base
│   ├── models.py              # SQLAlchemy-модели
│   ├── schemas.py             # Pydantic-схемы
│   ├── api/
│   │   └── routes.py          # REST API (опционально)
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── main.py            # запуск aiogram
│   │   ├── handlers.py
│   │   ├── keyboards.py
│   │   └── parser.py          # разбор быстрого ввода
│   ├── web/
│   │   ├── __init__.py
│   │   ├── routes.py          # FastAPI + Jinja2Templates
│   │   ├── templates/
│   │   │   ├── base.html
│   │   │   ├── dashboard.html
│   │   │   ├── reports.html
│   │   │   ├── categories.html
│   │   │   └── users.html
│   │   └── static/
│   │       ├── style.css
│   │       └── chart.umd.min.js   # если офлайн
│   └── services/
│       ├── stats.py           # агрегация для графиков
│       └── budgets.py
├── migrations/                # Alembic
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── deploy/
    ├── expense-bot.service
    └── expense-web.service
```

---

## 📦 requirements.txt

```txt
aiogram>=3.4
fastapi>=0.110
uvicorn[standard]>=0.29
jinja2>=3.1
sqlalchemy>=2.0
alembic>=1.13
python-dotenv>=1.0
pydantic>=2.6
```

---

## 🔐 Конфигурация (.env)

```env
# .env.example
BOT_TOKEN=123456:AA...              # токен от @BotFather
ALLOWED_TELEGRAM_IDS=111111,222222  # белый список
DB_PATH=/home/slava/expense-tracker/data/expenses.db
WEB_HOST=0.0.0.0
WEB_PORT=8080
TZ=Europe/Minsk
```

`.env` **обязательно** в `.gitignore`.

---

## 🚀 Этапы выполнения

### Этап 1. Подготовка Raspberry Pi
1. Подключиться по SSH: `ssh slava@<IP>`
2. Обновить систему: `sudo apt update && sudo apt upgrade -y`
3. Установить: `sudo apt install -y python3-venv python3-pip sqlite3 git`
4. Создать каталог: `/home/slava/expense-tracker`
5. Виртуальное окружение: `python3 -m venv venv && source venv/bin/activate`

### Этап 2. Backend + БД
1. Инициализировать git-репозиторий
2. Создать `requirements.txt`, установить зависимости
3. Реализовать модели SQLAlchemy + миграции Alembic
4. Создать начальные категории (Продукты, Транспорт, ЖКХ, Кафе, Развлечения, Здоровье, Связь, Прочее)
5. Реализовать сервис `stats.py` для агрегации данных

### Этап 3. Telegram-бот (aiogram)
1. Получить токен у `@BotFather`, положить в `.env`
2. Реализовать хендлеры, FSM, парсер быстрого ввода
3. Проверить белый список `telegram_id`
4. Ручное тестирование: добавить расходы, посмотреть отчёты

### Этап 4. Веб-интерфейс (FastAPI + Jinja2)
1. Настроить `Jinja2Templates(directory="app/web/templates")`
2. Реализовать роуты рендеринга страниц
3. Сверстать `base.html` с общим каркасом
4. Реализовать `dashboard.html` с 4 графиками Chart.js:
   - линейный (30 дней)
   - doughnut (по категориям)
   - горизонтальный бар (топ-5)
   - прогресс-бары бюджетов
5. Реализовать `reports.html` с фильтрами и экспортом CSV
6. Проверить отображение с телефона в LAN

### Этап 5. Развёртывание (systemd)

Создать два юнита:

**`/etc/systemd/system/expense-web.service`**
```ini
[Unit]
Description=Expense Tracker Web
After=network.target

[Service]
Type=simple
User=slava
WorkingDirectory=/home/slava/expense-tracker
Environment="PATH=/home/slava/expense-tracker/venv/bin"
ExecStart=/home/slava/expense-tracker/venv/bin/uvicorn app.web.routes:app --host 0.0.0.0 --port 8080
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/expense-bot.service`**
```ini
[Unit]
Description=Expense Tracker Bot
After=network.target

[Service]
Type=simple
User=slava
WorkingDirectory=/home/slava/expense-tracker
Environment="PATH=/home/slava/expense-tracker/venv/bin"
ExecStart=/home/slava/expense-tracker/venv/bin/python -m app.bot.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Активировать:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now expense-web expense-bot
sudo systemctl status expense-web expense-bot
```

### Этап 6. Тестирование
- Юнит-тесты для API и парсера быстрого ввода
- Ручная проверка бота в Telegram
- Проверка веб-сайта с другого устройства в LAN: `http://<IP_RPi>:8080`
- Проверка автозапуска после `sudo reboot`

### Этап 7. Документация
- `README.md`: установка, запуск, обновление, логи
- Скрипт бэкапа БД (cron → ежедневный дамп SQLite):
  ```bash
  0 3 * * * sqlite3 /home/slava/expense-tracker/data/expenses.db ".backup /home/slava/backups/expenses_$(date +\%F).db"
  ```

---

## 🔐 Безопасность

- [ ] Пароль SSH **не хранить** в репозитории
- [ ] Токен бота — только в `.env`, файл в `.gitignore`
- [ ] Доступ к веб-интерфейсу — только из локальной сети (`ufw` / nginx):
  ```
  sudo ufw allow from 192.168.0.0/24 to any port 8080
  ```
- [ ] Белый список `telegram_id` для бота


---

## ✅ Критерии готовности (Definition of Done)

- [ ] Бот принимает расходы (команды + быстрый ввод) и пишет в SQLite
- [ ] Веб-сайт открывается с любого устройства в LAN по `http://<IP_RPi>:8080`
- [ ] На дашборде отображаются: карточки сумм, линейный график, doughnut, топ-5, прогресс-бары, таблица трат
- [ ] Работает страница «Отчёты» с фильтрами и экспортом CSV
- [ ] Оба сервиса (`expense-web`, `expense-bot`) автоматически стартуют после перезагрузки RPi
- [ ] Есть `README.md`, `.env.example`, скрипт бэкапа БД
- [ ] Проверено на реальных данных членами семьи

---

## ❓ Что уточнить перед стартом

1. **Точный IP/хост** Raspberry Pi (уточнишь позже)
2. **Токен Telegram-бота** от `@BotFather`
3. **Список `telegram_id`** членов семьи (белый список)
4. **Валюта** по умолчанию (BYN?)
5. **Список категорий по умолчанию** и бюджеты по ним (если нужны)
6. **Нужен ли локальный `chart.umd.min.js`** в `static/` (если на RPi нет доступа в интернет)

---
