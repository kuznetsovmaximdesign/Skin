#!/usr/bin/env bash
# Ежемесячная проверка восстановления: берём последнюю копию, расшифровываем,
# разворачиваем и сравниваем с рабочей базой. Копия, которую ни разу не
# разворачивали, бэкапом не считается.
set -euo pipefail

: "${DB_PATH:?не задан DB_PATH}"
: "${LOCAL_DIR:?не задан LOCAL_DIR}"
: "${PASSPHRASE_FILE:?не задан PASSPHRASE_FILE}"
PYTHON="${PYTHON:-python3}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

archive=$(ls -1t "${LOCAL_DIR}"/life_bot_*.db.gpg 2>/dev/null | head -1)
[ -n "$archive" ] || { echo "копий нет в ${LOCAL_DIR}" >&2; exit 1; }

restored=$(mktemp /tmp/life_bot_restored.XXXXXX.db)
trap 'rm -f "$restored"' EXIT

gpg --batch --yes --quiet --decrypt \
    --passphrase-file "$PASSPHRASE_FILE" \
    --output "$restored" "$archive"

check=$("$PYTHON" "$HERE/dbtool.py" check "$restored")
[ "$check" = "ok" ] || { echo "восстановленная база битая: $check" >&2; exit 1; }

tables=$("$PYTHON" "$HERE/dbtool.py" tables "$restored")
restored_rows=$("$PYTHON" "$HERE/dbtool.py" count "$restored" inbox_raw)
live_rows=$("$PYTHON" "$HERE/dbtool.py" count "$DB_PATH" inbox_raw)

echo "копия:  $archive"
echo "таблиц: $tables"
echo "записей в inbox_raw: копия ${restored_rows}, рабочая ${live_rows}"
[ "$restored_rows" -le "$live_rows" ] || { echo "в копии записей больше, чем в рабочей базе" >&2; exit 1; }
echo "проверка пройдена"
