#!/usr/bin/env bash
# Ежедневный бэкап базы: снимок, шифрование, отправка, чистка старых копий.
# Настройки читаются из backup.env. Запускается таймером systemd.
set -euo pipefail

: "${DB_PATH:?не задан DB_PATH}"
: "${LOCAL_DIR:?не задан LOCAL_DIR}"
: "${PASSPHRASE_FILE:?не задан PASSPHRASE_FILE}"
REMOTE="${REMOTE:-}"
SSH_KEY="${SSH_KEY:-}"
KEEP_DAYS="${KEEP_DAYS:-30}"
PYTHON="${PYTHON:-python3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HC_URL="${HC_URL:-}"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
snapshot=$(mktemp /tmp/life_bot_snapshot.XXXXXX.db)
archive="${LOCAL_DIR}/life_bot_${stamp}.db.gpg"

cleanup() { rm -f "$snapshot"; }
trap cleanup EXIT

fail() {
    echo "бэкап не сделан: $1" >&2
    [ -n "$HC_URL" ] && curl -fsS -m 10 --data-raw "$1" "${HC_URL}/fail" >/dev/null || true
    exit 1
}

mkdir -p "$LOCAL_DIR"
chmod 700 "$LOCAL_DIR"

# 1. Снимок. Именно .backup, а не копирование файла: база в WAL, и обычный
#    cp даёт рассогласованную копию.
"$PYTHON" "$HERE/dbtool.py" snapshot "$DB_PATH" "$snapshot" || fail "снимок не снялся"

# 2. Снимок должен открываться и проходить проверку целостности.
check=$("$PYTHON" "$HERE/dbtool.py" check "$snapshot" || echo "ошибка")
[ "$check" = "ok" ] || fail "снимок битый: $check"

rows=$("$PYTHON" "$HERE/dbtool.py" count "$snapshot" inbox_raw)

# 3. Шифрование. На сервер-приёмник уезжает только шифротекст.
gpg --batch --yes --quiet \
    --symmetric --cipher-algo AES256 \
    --passphrase-file "$PASSPHRASE_FILE" \
    --output "$archive" "$snapshot" || fail "не зашифровалось"
chmod 600 "$archive"

# 4. Отправка на второй хост. Без неё это не бэкап, а копия рядом с оригиналом.
if [ -n "$REMOTE" ]; then
    ssh_opts=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new)
    [ -n "$SSH_KEY" ] && ssh_opts+=(-i "$SSH_KEY")
    scp "${ssh_opts[@]}" "$archive" "$REMOTE/" || fail "не уехало на $REMOTE"
fi

# 5. Чистка старых копий локально.
find "$LOCAL_DIR" -name 'life_bot_*.db.gpg' -mtime "+${KEEP_DAYS}" -delete

size=$(stat -c %s "$archive")
echo "бэкап готов: $archive, ${size} байт, записей в inbox_raw: ${rows}"
[ -n "$HC_URL" ] && curl -fsS -m 10 "$HC_URL" >/dev/null || true
