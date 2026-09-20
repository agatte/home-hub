#!/bin/bash
# Daily SQLite backup — safe to run while the backend is serving.
#
# SQLite's .backup command uses the backup API which handles locking
# correctly even with active aiosqlite connections.
#
# Install as cron on the Latitude:
#   crontab -e
#   0 4 * * * /home/anthony/home-hub/scripts/backup-db.sh
#
# Or as a systemd timer (see deployment/home-hub-backup.timer).

set -euo pipefail

DB_PATH="${HOME}/home-hub/data/home_hub.db"
BACKUP_DIR="${HOME}/home-hub/data/backups"
RETENTION_DAYS=7

mkdir -p "$BACKUP_DIR"

if [ ! -f "$DB_PATH" ]; then
    echo "Database not found at $DB_PATH"
    exit 1
fi

BACKUP_FILE="$BACKUP_DIR/home_hub_$(date +%Y%m%d_%H%M%S).db"
PARTIAL_FILE="${BACKUP_FILE}.partial"
BACKUP_ATTEMPTS=3
BACKUP_BUSY_TIMEOUT_MS=60000
BACKUP_RETRY_DELAY_SECONDS=10

# Never publish a partial/corrupt file under the normal backup filename.
# The trap also cleans interrupted runs so retention/verification cannot mistake
# a failed extraction for a usable backup.
trap 'rm -f "$PARTIAL_FILE"' EXIT

backup_ok=0
for attempt in $(seq 1 "$BACKUP_ATTEMPTS"); do
    rm -f "$PARTIAL_FILE"
    if sqlite3 "$DB_PATH" \
        ".timeout $BACKUP_BUSY_TIMEOUT_MS" \
        ".backup '$PARTIAL_FILE'"; then
        backup_ok=1
        break
    fi

    echo "Backup attempt $attempt/$BACKUP_ATTEMPTS could not acquire a stable database lock."
    if [ "$attempt" -lt "$BACKUP_ATTEMPTS" ]; then
        sleep "$BACKUP_RETRY_DELAY_SECONDS"
    fi
done

if [ "$backup_ok" -ne 1 ]; then
    echo "Backup failed after $BACKUP_ATTEMPTS attempts."
    exit 1
fi

CHECK_RESULT="$(sqlite3 "$PARTIAL_FILE" "PRAGMA quick_check;")"
if [ "$CHECK_RESULT" != "ok" ]; then
    echo "Backup verification failed: PRAGMA quick_check returned: $CHECK_RESULT"
    exit 1
fi

mv "$PARTIAL_FILE" "$BACKUP_FILE"
trap - EXIT

# Remove completed backups older than retention period.
find "$BACKUP_DIR" -name "home_hub_*.db" -mtime +${RETENTION_DAYS} -delete

echo "Backup complete + quick_check=ok: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
