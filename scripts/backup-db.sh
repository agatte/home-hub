#!/bin/bash
# Daily verified SQLite backup for the Latitude.
#
# Home Hub writes continuously and currently uses SQLite DELETE journaling.
# Online .backup was proven to thrash/restart under that workload on 2026-09-20,
# so this script briefly quiesces only home-hub.service, creates + verifies the
# backup, then restores the service and requires /health before success.
#
# Install as cron on the Latitude (scheduled away from the 04:00 ML job):
#   30 4 * * * /home/anthony/home-hub/scripts/backup-db.sh

set -euo pipefail

DB_PATH="${HOME}/home-hub/data/home_hub.db"
BACKUP_DIR="${HOME}/home-hub/data/backups"
SERVICE_NAME="home-hub.service"
HEALTH_URL="http://localhost:8000/health"
RETENTION_DAYS=7
HEALTH_WAIT_SECONDS=45

# Cron does not reliably inherit the user systemd session environment.
USER_ID="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$USER_ID}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"

mkdir -p "$BACKUP_DIR"

# Refuse overlapping runs, then clear only proven scratch residue from a prior
# failed/interrupted backup.
exec 9>"$BACKUP_DIR/.backup.lock"
if ! flock -n 9; then
    echo "Backup already running; refusing overlapping execution."
    exit 1
fi
rm -f "$BACKUP_DIR"/home_hub_*.partial "$BACKUP_DIR"/home_hub_*.partial-journal

if [ ! -f "$DB_PATH" ]; then
    echo "Database not found at $DB_PATH"
    exit 1
fi

BACKUP_FILE="$BACKUP_DIR/home_hub_$(date +%Y%m%d_%H%M%S).db"
PARTIAL_FILE="${BACKUP_FILE}.partial"
SERVICE_STOPPED_BY_BACKUP=0

cleanup() {
    rm -f "$PARTIAL_FILE" "$PARTIAL_FILE-journal"
    if [ "$SERVICE_STOPPED_BY_BACKUP" -eq 1 ]; then
        echo "Restoring $SERVICE_NAME after backup exit..."
        systemctl --user start "$SERVICE_NAME" || \
            echo "ERROR: could not restart $SERVICE_NAME during cleanup."
    fi
}
trap cleanup EXIT

# Continuous application writes made online .backup restart/thrash in DELETE
# journal mode. Quiesce only the main backend; unrelated user services remain
# untouched. If this script exits unexpectedly, the EXIT trap restores it.
if systemctl --user is-active --quiet "$SERVICE_NAME"; then
    SERVICE_STOPPED_BY_BACKUP=1
    echo "Stopping $SERVICE_NAME for a consistent database backup..."
    systemctl --user stop "$SERVICE_NAME"
fi

sqlite3 "$DB_PATH" ".backup '$PARTIAL_FILE'"

CHECK_RESULT="$(sqlite3 "$PARTIAL_FILE" "PRAGMA quick_check;")"
if [ "$CHECK_RESULT" != "ok" ]; then
    echo "Backup verification failed: PRAGMA quick_check returned: $CHECK_RESULT"
    exit 1
fi

mv "$PARTIAL_FILE" "$BACKUP_FILE"

# Restore the backend to its pre-backup active state and require its health
# endpoint before this run is allowed to report success.
if [ "$SERVICE_STOPPED_BY_BACKUP" -eq 1 ]; then
    echo "Starting $SERVICE_NAME..."
    systemctl --user start "$SERVICE_NAME"

    healthy=0
    for _ in $(seq 1 "$HEALTH_WAIT_SECONDS"); do
        if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
            healthy=1
            break
        fi
        sleep 1
    done
    if [ "$healthy" -ne 1 ]; then
        echo "Backup succeeded, but $SERVICE_NAME did not become healthy within ${HEALTH_WAIT_SECONDS}s."
        exit 1
    fi
    SERVICE_STOPPED_BY_BACKUP=0
fi

# Remove completed backups older than retention period.
find "$BACKUP_DIR" -name "home_hub_*.db" -mtime +${RETENTION_DAYS} -delete

trap - EXIT
echo "Backup complete + quick_check=ok + backend healthy: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
