#!/usr/bin/env bash
# Ежедневный бэкап SQLite-базы «Семейные расходы».
#
# Использование:
#   ./deploy/backup_db.sh                       # пути по умолчанию (см. ниже)
#   DB_PATH=/path/expenses.db BACKUP_DIR=/mnt/usb/backups ./deploy/backup_db.sh
#
# Переменные окружения:
#   DB_PATH     — путь к базе            (по умолчанию /home/slava/expense-tracker/data/expenses.db)
#   BACKUP_DIR  — каталог для копий      (по умолчанию /home/slava/backups)
#   KEEP_DAYS   — сколько дней хранить   (по умолчанию 14, 0 = хранить вечно)
#
# Cron (ежедневно в 3:00):
#   0 3 * * * /home/slava/expense-tracker/deploy/backup_db.sh >> /home/slava/backups/backup.log 2>&1
#
# Копия делается через SQLite Backup API (безопасно при работающих сервисах,
# учитывает WAL). Скрипт не удаляет саму базу и никогда не пишет в DB_PATH.

set -euo pipefail

DB_PATH="${DB_PATH:-/home/slava/expense-tracker/data/expenses.db}"
BACKUP_DIR="${BACKUP_DIR:-/home/slava/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

log() {
    echo "[$(date '+%F %T')] $*"
}

if [[ ! -f "$DB_PATH" ]]; then
    log "ОШИБКА: база не найдена: $DB_PATH"
    exit 1
fi

mkdir -p "$BACKUP_DIR"
TARGET="${BACKUP_DIR}/expenses_$(date '+%F_%H%M%S').db"

if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$DB_PATH" ".backup '${TARGET}'"
    integrity="$(sqlite3 "$TARGET" 'PRAGMA integrity_check;')"
else
    # sqlite3 CLI не установлен — используем стандартную библиотеку Python.
    python3 - "$DB_PATH" "$TARGET" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1], sys.argv[2]
with sqlite3.connect(source_path) as source, sqlite3.connect(target_path) as target:
    source.backup(target)
PY
    integrity="$(python3 -c "import sqlite3, sys; print(sqlite3.connect(sys.argv[1]).execute('PRAGMA integrity_check;').fetchone()[0])" "$TARGET")"
fi

if [[ "$integrity" != "ok" ]]; then
    log "ОШИБКА: копия повреждена ($integrity): $TARGET"
    exit 1
fi

log "бэкап готов: $TARGET ($(du -h "$TARGET" | cut -f1)), integrity_check=$integrity"

if [[ "$KEEP_DAYS" -gt 0 ]]; then
    # Удаляем только собственные копии, базу и чужие файлы не трогаем.
    find "$BACKUP_DIR" -maxdepth 1 -type f -name 'expenses_*.db' -mtime "+${KEEP_DAYS}" -print -delete \
        | while read -r removed; do log "удалён старый бэкап: $removed"; done
fi
