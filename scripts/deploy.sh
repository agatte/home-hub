#!/usr/bin/env bash
#
# Home Hub deployment script.
#
# Pulls latest from origin, rebuilds/reinstalls based on what actually
# changed, and restarts systemd user services as needed. Run on the
# Latitude (production machine), typically after `git push` from the
# dev machine.
#
# Usage:
#   ./scripts/deploy.sh
#
# Exit codes:
#   0 — success (or no changes)
#   1 — deploy failed (health check, git pull conflict, etc.)

set -euo pipefail

# Ensure systemctl --user works when invoked over SSH (SSH sessions don't
# always inherit the DBus session bus address from the desktop session).
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

# Move to repo root regardless of where this script was invoked from.
cd "$(dirname "$0")/.."

OLD_HEAD=$(git rev-parse HEAD)
git pull --ff-only
NEW_HEAD=$(git rev-parse HEAD)

if [[ "$OLD_HEAD" == "$NEW_HEAD" ]]; then
    echo "No changes. Nothing to deploy."
    exit 0
fi

echo "Deploying ${OLD_HEAD:0:7} → ${NEW_HEAD:0:7}"
echo

CHANGED=$(git diff --name-only "$OLD_HEAD" "$NEW_HEAD")
echo "Changed files:"
echo "$CHANGED" | sed 's/^/  /'
echo

RESTART_BACKEND=0
RESTART_AMBIENT=0
REBUILD_FRONTEND=0

if echo "$CHANGED" | grep -q "^requirements\.txt$"; then
    echo "→ requirements.txt changed; reinstalling Python deps..."
    ./venv/bin/pip install -r requirements.txt
    RESTART_BACKEND=1
fi

if echo "$CHANGED" | grep -qE "^frontend-svelte/(package\.json|package-lock\.json)$"; then
    echo "→ frontend package manifest changed; running npm install..."
    (cd frontend-svelte && npm install)
    REBUILD_FRONTEND=1
fi

if echo "$CHANGED" | grep -qE "^frontend-svelte/(src|static)/"; then
    REBUILD_FRONTEND=1
fi

if [[ "$REBUILD_FRONTEND" == "1" ]]; then
    echo "→ Rebuilding frontend..."
    (cd frontend-svelte && npm run build)
fi

if echo "$CHANGED" | grep -qE "^(backend/|run\.py$)"; then
    RESTART_BACKEND=1
fi

if echo "$CHANGED" | grep -q "^backend/services/pc_agent/ambient_monitor\.py$"; then
    RESTART_AMBIENT=1
fi

if [[ "$RESTART_BACKEND" == "1" ]]; then
    echo "→ Restarting home-hub.service..."
    systemctl --user restart home-hub.service
    sleep 3
    if ! curl -sf http://localhost:8000/health > /dev/null; then
        echo "✗ Health check failed after backend restart!"
        echo
        systemctl --user status home-hub.service --no-pager | tail -20
        exit 1
    fi
    echo "  ✓ Backend healthy"
fi

if [[ "$RESTART_AMBIENT" == "1" ]]; then
    echo "→ Restarting home-hub-ambient.service..."
    systemctl --user restart home-hub-ambient.service
fi

echo
echo "✓ Deploy complete."
