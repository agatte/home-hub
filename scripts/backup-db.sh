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

# Never publish a partial/corrupt file under the normal backup filename.
# The trap also cleans interrupted runs so retention/verification cannot mistake
# a failed extraction for a usable backup.
trap 'rm -f "$PARTIAL_FILE"' EXIT
sqlite3 "$DB_PATH" ".backup '$PARTIAL_FILE'"

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
