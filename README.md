# 💰 Семейные расходы

Гибридное приложение для домашнего учёта трат: Telegram-бот для ввода расходов
членами семьи и веб-интерфейс со статистикой и графиками, работающий в локальной
сети. Всё хранится в одном файле SQLite, оба сервиса автозапускаются через systemd
на Raspberry Pi.

```
 Telegram ──▶ aiogram-бот ─┐
                           ├──▶ SQLite (data/expenses.db) ◀── Alembic (миграции)
 Браузер  ──▶ FastAPI+Jinja┘
```

## ✨ Возможности

**Telegram-бот (aiogram 3)**

| Команда | Действие |
|---------|----------|
| `/start` | Регистрация в БД + краткая инструкция |
| `/add` | Интерактивное добавление: сумма → категория → комментарий (FSM) |
| `/today` | Сумма расходов за сегодня |
| `/month` | Отчёт за текущий месяц |
| `/stats` (`/top`) | Топ категорий за месяц |
| `/categories` (`/cats`) | Список категорий (с суммами за месяц) |
| `/budget` | Прогресс лимитов текущего месяца |
| `/addcat <название> <эмодзи>` | Добавить категорию (только админ) |
| `/id` | Показать свой `telegram_id` (для белого списка) |
| `/cancel` | Отменить текущее действие |
| `/help` | Справка |

Плюс **быстрый ввод одной строкой** — достаточно написать сообщение:

```
500 продукты хлеб и молоко     → 500.00 BYN, категория «Продукты», комментарий «хлеб и молоко»
1 500 такси домой              → разбор суммы с пробелами и синонима («такси» → «Транспорт»)
300,50 еда обед                → «еда» — синоним категории «Продукты»
```

Доступ ограничивается белым списком `ALLOWED_TELEGRAM_IDS`; категории добавляют
только админы (`ADMIN_TELEGRAM_IDS`).

**Веб-интерфейс (FastAPI + Jinja2 + Chart.js)** — `http://<IP>:8080`

| Страница | Что показывает |
|----------|----------------|
| `/` Дашборд | Карточки (сегодня / месяц / средний день / остаток по бюджету), линейный график за 30 дней, doughnut по категориям, топ-5, прогресс-бары бюджетов, последние траты |
| `/expenses` | Список трат с фильтрами (период, категория, участник, поиск), постранично, формы добавления и удаления |
| `/reports` | Сводка и сравнение периодов, суммы по дням/месяцам/категориям, экспорт в CSV (`/reports/export.csv`) |
| `/categories` | Создание, переименование, эмодзи, синонимы, включение/отключение категорий |
| `/users` | Траты по членам семьи |
| `/api/docs` | Swagger UI по JSON API (`/api/*`) |

Авторизации в веб-интерфейсе нет — он рассчитан на доступ только из домашней
сети (см. раздел «Безопасность»).

## 🧱 Стек

| Слой | Технология |
|------|------------|
| Язык | Python 3.11+ (проверено на 3.14) |
| Telegram-бот | aiogram 3 (FSM, inline-клавиатуры) |
| Веб / API | FastAPI + uvicorn + Jinja2 |
| Графики | Chart.js 4 (локальная копия или CDN) |
| БД | SQLite (WAL, `PRAGMA foreign_keys=ON`) |
| ORM / миграции | SQLAlchemy 2 + Alembic |
| Автозапуск | systemd (Raspberry Pi OS / Ubuntu Server) |

## 📁 Структура проекта

```
app/
  config.py          # настройки из .env (единый объект settings)
  database.py        # engine, SessionLocal, init_db(), session_scope()
  models.py          # User, Category, Expense, Budget
  schemas.py         # pydantic-схемы API
  formatting.py      # деньги, даты, склонения для шаблонов и бота
  timeutils.py       # границы дня/месяца, учёт таймзоны
  bot/
    main.py          # точка входа бота, команды Telegram
    handlers.py      # хендлеры команд, быстрый ввод, FSM /add
    middlewares.py   # сессия БД + белый список telegram_id
    keyboards.py     # reply/inline-клавиатуры
    parser.py        # разбор «500 продукты хлеб и молоко»
  services/          # бизнес-логика: expenses, categories, budgets, stats
  web/
    routes.py        # FastAPI-приложение, страницы, CSV-экспорт
    api/routes.py    # JSON API /api/* (Swagger на /api/docs)
    templates/       # base, dashboard, expenses, reports, categories, users
    static/style.css
alembic/             # миграции (0001_initial_schema — текущая голова)
tests/               # pytest: сервисы, статистика, парсер, API, веб
deploy/              # systemd-юниты и скрипт бэкапа
.gitattributes       # фиксирует LF-переводы строк для .sh/.service/*.py/*.md
run_bot.py           # python run_bot.py
run_web.py           # python run_web.py (host/port из .env)
devcheck_bot.py      # смоук-проверка бота без токена
devcheck_web.py      # смоук-проверка веб-слоя без токена
task.md              # исходное ТЗ
```

## 🚀 Быстрый старт

### Raspberry Pi / Linux

```bash
cd /home/slava/expense-tracker          # каталог с проектом
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt          # для тестов: -r requirements-dev.txt
cp .env.example .env && nano .env        # впишите BOT_TOKEN и белый список id
python -m alembic upgrade head           # создаёт схему БД и таблицу alembic_version
python run_web.py                        # http://<IP>:8080  (Ctrl+C — остановить)
python run_bot.py                        # во втором терминале
```

### Windows (локальная отладка)

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env              # затем откройте .env и заполните
python -m alembic upgrade head
python run_web.py                        # http://127.0.0.1:8080
python run_bot.py
```

Для локальной отладки удобно указать в `.env` относительный путь к базе:

```
DB_PATH=data/expenses.db
```

Каталог `data/` создаётся автоматически при первом запуске.

## ⚙️ Настройка `.env`

`.env` лежит в корне проекта, **не коммитится** (см. `.gitignore`) и читается через
python-dotenv (`app/config.py`). Шаблон — `.env.example`.

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `BOT_TOKEN` | — | Токен от [@BotFather](https://t.me/BotFather). Без него бот не стартует |
| `ALLOWED_TELEGRAM_IDS` | пусто | Белый список id через запятую. **Пусто = доступ всем** (только для отладки) |
| `ADMIN_TELEGRAM_IDS` | пусто | Кто может `/addcat`. Пусто = все из белого списка |
| `DB_PATH` | `data/expenses.db` | Абсолютный путь к SQLite-файлу на RPi: `/home/slava/expense-tracker/data/expenses.db` |
| `WEB_HOST` | `0.0.0.0` | Интерфейс прослушивания (`run_web.py`) |
| `WEB_PORT` | `8080` | Порт веб-интерфейса |
| `TZ` | `Europe/Minsk` | Таймзона для «сегодня»/«месяца» |
| `DEFAULT_CURRENCY` | `BYN` | Валюта по умолчанию |
| `LOG_LEVEL` | `INFO` | Уровень логирования (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `SEED_DEFAULT_CATEGORIES` | `1` | Создавать категории по умолчанию при инициализации БД |

Свой `telegram_id` можно узнать командой `/id` в боте.

При старте (веб — через lifespan, бот — `setup_database()`) приложение вызывает
`init_db()`: создаёт отсутствующие таблицы и **идемпотентно** добавляет категории
по умолчанию. Уже изменённые, переименованные или отключённые вами категории не
перезаписываются.

## 🗄️ База данных и миграции

Схема описана в `app/models.py`, миграции — в `alembic/versions/` (источник истины
для изменений схемы). Обычные команды:

```bash
python -m alembic current                       # на какой ревизии база
python -m alembic upgrade head                  # применить все миграции
python -m alembic downgrade -1                  # откатить одну
python -m alembic check                         # «нет дрейфа» между моделями и схемой
python -m alembic revision --autogenerate -m "Добавил поле"
```

⚠️ **Порядок важен при первой установке.** Миграция `0001_initial_schema` создаёт
таблицы, поэтому на пустой базе сначала выполните `python -m alembic upgrade head`,
а уже потом запускайте сервисы. Если база была создана приложением раньше
(`init_db()` → `CREATE TABLE`) и таблицы уже есть, отметить её как актуальную нужно
без выполнения DDL:

```bash
python -m alembic stamp head
```

После этого `python -m alembic check` должен отвечать «No new upgrade operations
detected» — это проверено на реальной базе.

Полезные детали:

* SQLite включается с `PRAGMA foreign_keys=ON` и `journal_mode=WAL`
  (`app/database.py`) — рядом с базой появляются файлы `*.db-wal` и `*.db-shm`.
* Все даты хранятся в UTC (`spent_at`, `created_at`), а «сегодня» и «месяц»
  считаются в таймзоне `TZ` (`app/timeutils.py`).
* Резервная копия — это просто копия файла базы (см. раздел «Бэкап»).

## ▶️ Запуск

### Веб-интерфейс

```bash
python run_web.py
# эквивалент (то, что запускает systemd):
uvicorn app.web.routes:app --host 0.0.0.0 --port 8080
```

Открывайте `http://<IP_RPi>:8080` с телефона или компьютера в той же сети.
Документация API — `http://<IP_RPi>:8080/api/docs` (JSON API живёт под `/api/*`:
`/api/health`, `/api/expenses`, `/api/categories`, `/api/budgets`, `/api/users`,
`/api/stats/summary|compare|daily|monthly|categories`).

### Telegram-бот

```bash
python run_bot.py
# эквивалент:
python -m app.bot.main
```

Без `BOT_TOKEN` процесс завершится с сообщением
«BOT_TOKEN не задан: скопируйте .env.example в .env и впишите токен».

### Страницы веб-интерфейса

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/` | дашборд |
| GET/POST | `/expenses` | список трат с фильтрами / добавить трату |
| POST | `/expenses/{id}/delete` | удалить трату |
| GET | `/reports` | отчёты и сравнение периодов |
| GET | `/reports/export.csv` | экспорт выборки в CSV |
| GET/POST | `/categories` | список / создать категорию |
| POST | `/categories/{id}` | изменить категорию |
| POST | `/categories/{id}/delete` | удалить или отключить категорию |
| GET | `/users` | траты по членам семьи |
| POST | `/budgets` | сохранить лимиты на месяц |

## 🧪 Тесты и проверки

```bash
pip install -r requirements-dev.txt
python -m pytest                 # весь набор (109 тестов, ~10 с)
python -m pytest tests/test_web.py -v
python -m pytest -k parser
```

Дополнительные смоук-проверки на временной БД (не трогают `data/expenses.db`):

```bash
python devcheck_web.py     # рендер страниц, формы, CSV, JSON API
python devcheck_bot.py     # импорт модулей, хендлеры, парсер, статистика
```

## 🍓 Развёртывание на Raspberry Pi

Целевой сервер: Raspberry Pi OS / Ubuntu Server, IP **`192.168.100.79`**,
пользователь `slava`, каталог `/home/slava/expense-tracker`, порт `8080`,
репозиторий <https://github.com/KViachaslav/expenses_tracking.git>.
Пароль SSH и токен бота — в локальном `NOTES.local.md` (файл в `.gitignore`,
в репозиторий секреты не попадают).

### 1. Код и виртуальное окружение

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip sqlite3 git
git clone https://github.com/KViachaslav/expenses_tracking.git /home/slava/expense-tracker
cd /home/slava/expense-tracker
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

### 2. База и `.env`

```bash
cp .env.example .env
nano .env        # BOT_TOKEN, ALLOWED_TELEGRAM_IDS, ADMIN_TELEGRAM_IDS,
                 # DB_PATH=/home/slava/expense-tracker/data/expenses.db, TZ
chmod 600 .env
./venv/bin/python -m alembic upgrade head
```

### 3. systemd

Готовые юниты лежат в `deploy/`. Перед копированием проверьте в них `User`,
`WorkingDirectory`, `EnvironmentFile` и путь к `venv`:

```bash
sudo cp deploy/expense-web.service deploy/expense-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now expense-web expense-bot
systemctl status expense-web expense-bot --no-pager
```

> ⚠️ Файлы `deploy/*.service`, `deploy/*.sh` и `.env` должны иметь **LF**-переводы
> строк: CRLF ломает `ExecStart`/`EnvironmentFile` в systemd и shebang bash.
> Переводы строк фиксирует `.gitattributes`; при ручной правке из Windows
> сохраняйте файлы как LF (в VS Code — статус `LF` в правом нижнем углу).
> Проверить в Linux: `file deploy/expense-web.service` (не должно быть «CRLF»).

Проверка автозапуска:

```bash
sudo reboot
# после загрузки:
systemctl is-active expense-web expense-bot
curl -s http://127.0.0.1:8080/api/health
```

### 4. Доступ только из локальной сети

```bash
sudo apt install -y ufw
sudo ufw allow from 192.168.0.0/24 to any port 8080 proto tcp
sudo ufw enable
```

У веб-интерфейса нет авторизации, поэтому не пробрасывайте порт 8080 в интернет
(без проброса на роутере сайт доступен только внутри дома).

## 💾 Бэкап и восстановление

Готовый скрипт: `deploy/backup_db.sh` (копия делается через SQLite Backup API,
поэтому работает и при запущенных сервисах, учитывает WAL, проверяет
`integrity_check` и удаляет копии старше `KEEP_DAYS` дней).

```bash
chmod +x deploy/backup_db.sh
DB_PATH=/home/slava/expense-tracker/data/expenses.db \
BACKUP_DIR=/home/slava/backups ./deploy/backup_db.sh
```

Ежедневный запуск в 3:00 через cron:

```cron
0 3 * * * /home/slava/expense-tracker/deploy/backup_db.sh >> /home/slava/backups/backup.log 2>&1
```

Восстановление — остановить сервисы, подменить файл базы, запустить снова:

```bash
sudo systemctl stop expense-bot expense-web
cp /home/slava/backups/expenses_2026-08-01_030000.db \
   /home/slava/expense-tracker/data/expenses.db
rm -f /home/slava/expense-tracker/data/expenses.db-wal \
      /home/slava/expense-tracker/data/expenses.db-shm
sudo systemctl start expense-web expense-bot
```

## ⬆️ Обновление версии

```bash
cd /home/slava/expense-tracker
./venv/bin/pip install -r requirements.txt     # подтянуть новые зависимости
./venv/bin/python -m alembic upgrade head      # применить миграции
sudo systemctl restart expense-web expense-bot
```

Перед обновлением стоит сделать бэкап: `./deploy/backup_db.sh`.

## 📜 Логи и диагностика

```bash
journalctl -u expense-web -f          # логи веб-сервиса в реальном времени
journalctl -u expense-bot -n 100      # последние 100 строк лога бота
journalctl -u expense-web --since today
```

Частые ситуации:

| Симптом | Причина и решение |
|---------|-------------------|
| Бот сразу завершается | Не задан `BOT_TOKEN` в `.env` (или сервис запущен не из каталога проекта) |
| Бот молчит в ответ на сообщения | Ваш `telegram_id` не в `ALLOWED_TELEGRAM_IDS`; узнайте id командой `/id` и добавьте его |
| `/addcat` не работает | Пользователь не админ: заполните `ADMIN_TELEGRAM_IDS` |
| Сайт не открывается с телефона | Проверьте `systemctl status expense-web`, правило `ufw` и что телефон в той же сети; `curl http://127.0.0.1:8080/api/health` должен отвечать `{"status":"ok",...}` |
| Адрес занят (`address already in use`) | Порт 8080 занят другим процессом: `sudo ss -tulpn | grep 8080` |
| Графики не рисуются | Нет доступа в интернет к CDN: положите `chart.umd.min.js` в `app/web/static/` — локальная копия имеет приоритет |
| «No such table: users» | Не применены миграции: `./venv/bin/python -m alembic upgrade head` |
| Суммы в отчётах за день не совпадают с ожиданием | Проверьте `TZ` в `.env` (по умолчанию `Europe/Minsk`), даты хранятся в UTC |

## 🔐 Безопасность

* Токен бота и `telegram_id` храните только в `.env` (он в `.gitignore`) — не
  коммитьте секреты и не публикуйте их в переписке.
* Обязательно заполните `ALLOWED_TELEGRAM_IDS`: пустое значение открывает бота всем.
* Веб-интерфейс без авторизации — держите его в локальной сети и ограничьте
  доступ через `ufw` или обратный прокси.
* Файл базы стоит закрыть от посторонних: `chmod 640 data/expenses.db`.

## 📄 Лицензия

Домашний проект, распространяется как есть (см. `task.md` — исходное ТЗ).
