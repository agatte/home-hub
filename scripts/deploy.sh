#!/usr/bin/env bash
#
# Home Hub deployment script.
#
# Pulls latest from origin, rebuilds/reinstalls based on what actually
# changed since the last successful deploy, and restarts systemd user
# services as needed. Run on the Latitude (production machine), typically
# after `git push` from the dev machine.
#
# State: tracks the last-deployed SHA in .last-deployed-sha (gitignored,
# repo root). This makes the script idempotent against pre-pulled trees
# (e.g. `git pull && ./scripts/deploy.sh` no longer self-cancels) and
# against re-runs after a partial failure.
#
# Usage:
#   ./scripts/deploy.sh
#
# Exit codes:
#   0 — success (or already up-to-date)
#   1 — deploy failed (health check, git pull conflict, etc.)

set -euo pipefail

# Ensure systemctl --user works when invoked over SSH (SSH sessions don't
# always inherit the DBus session bus address from the desktop session).
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

# Move to repo root regardless of where this script was invoked from.
cd "$(dirname "$0")/.."

MARKER=".last-deployed-sha"

# Read the last-deployed SHA from the marker file. Empty if missing or
# the recorded SHA is no longer in git history (force-push / fresh clone).
LAST_DEPLOYED=""
if [[ -f "$MARKER" ]]; then
    candidate=$(cat "$MARKER" | tr -d '[:space:]')
    if [[ -n "$candidate" ]] && git cat-file -e "${candidate}^{commit}" 2>/dev/null; then
        LAST_DEPLOYED="$candidate"
    else
        echo "Warning: $MARKER points at $candidate which isn't in git history; treating as full rebuild."
    fi
fi

git pull --ff-only
NEW_HEAD=$(git rev-parse HEAD)

if [[ -n "$LAST_DEPLOYED" && "$LAST_DEPLOYED" == "$NEW_HEAD" ]]; then
    echo "Already deployed at ${NEW_HEAD:0:7}. Nothing to do."
    exit 0
fi

RESTART_BACKEND=0
RESTART_AMBIENT=0
REBUILD_FRONTEND=0

if [[ -z "$LAST_DEPLOYED" ]]; then
    # First-time deploy on this machine (or marker was reset). Rebuild
    # everything and reinstall deps to guarantee a clean state.
    echo "First-time deploy at ${NEW_HEAD:0:7} — rebuilding everything"
    echo
    echo "→ Reinstalling Python deps..."
    ./venv/bin/pip install -r requirements.txt
    echo "→ Running npm install..."
    (cd frontend-svelte && npm install)
    REBUILD_FRONTEND=1
    RESTART_BACKEND=1
    RESTART_AMBIENT=1
else
    echo "Deploying ${LAST_DEPLOYED:0:7} → ${NEW_HEAD:0:7}"
    echo

    CHANGED=$(git diff --name-only "$LAST_DEPLOYED" "$NEW_HEAD")
    echo "Changed files:"
    echo "$CHANGED" | sed 's/^/  /'
    echo

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

    if echo "$CHANGED" | grep -qE "^(backend/|run\.py$)"; then
        RESTART_BACKEND=1
    fi

    if echo "$CHANGED" | grep -q "^backend/services/pc_agent/ambient_monitor\.py$"; then
        RESTART_AMBIENT=1
    fi
fi

if [[ "$REBUILD_FRONTEND" == "1" ]]; then
    echo "→ Rebuilding frontend..."
    (cd frontend-svelte && npm run build)
    # Frontend is served by the backend — restart it so the kiosk sees
    # a new build_id and auto-reloads via WebSocket.
    RESTART_BACKEND=1
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

# Record success — only reached if every step above passed (set -e).
echo "$NEW_HEAD" > "$MARKER"

echo
echo "✓ Deploy complete."
