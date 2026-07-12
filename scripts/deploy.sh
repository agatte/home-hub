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
# On post-restart health-check failure, the script rolls back to the
# previously-deployed SHA, re-runs the same install / rebuild steps,
# and restarts again. Recovery is best-effort — if rollback also fails,
# the script exits 2 and the system is left in a broken state for
# manual recovery. Auto-rollback only fires when LAST_DEPLOYED is
# known; first-time deploys exit 1 like before with no rollback path.
#
# Exit codes:
#   0 — success (or already up-to-date)
#   1 — deploy failed; system was rolled back to last known good SHA
#       (or first-time deploy failed and there was nothing to roll back to)
#   2 — deploy AND rollback failed; system is broken, manual recovery needed

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
RESTART_LATITUDE_STREAMING=0
RESTART_TUNNEL=0
INSTALL_KIOSK_RECYCLE=0
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
    RESTART_LATITUDE_STREAMING=1
    RESTART_TUNNEL=1
    INSTALL_KIOSK_RECYCLE=1
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

    if echo "$CHANGED" | grep -qE "^(scripts/recycle-kiosk\.sh|deployment/home-hub-kiosk-recycle\.(service|timer))$"; then
        INSTALL_KIOSK_RECYCLE=1
    fi

    if echo "$CHANGED" | grep -qE "^(backend/|run\.py$)"; then
        RESTART_BACKEND=1
    fi

    if echo "$CHANGED" | grep -q "^backend/services/pc_agent/ambient_monitor\.py$"; then
        RESTART_AMBIENT=1
    fi

    if echo "$CHANGED" | grep -qE "^(backend/services/pc_agent/latitude_streaming_detector\.py|deployment/home-hub-latitude-streaming\.service)$"; then
        RESTART_LATITUDE_STREAMING=1
    fi

    # Tunnel proxy is its own uvicorn process — restart when its sources
    # or the auth gate it relies on change.
    if echo "$CHANGED" | grep -qE "^backend/api/(tunnel_proxy|auth)\.py$"; then
        RESTART_TUNNEL=1
    fi
fi

if [[ "$REBUILD_FRONTEND" == "1" ]]; then
    echo "→ Rebuilding frontend..."
    (cd frontend-svelte && npm run build)
    # Frontend is served by the backend — restart it so the kiosk sees
    # a new build_id and auto-reloads via WebSocket.
    RESTART_BACKEND=1
fi

# Poll /health for up to 20s. Returns 0 when /health responds with HTTP
# 2xx, 1 if the timeout elapses without a successful response. Used both
# for the forward deploy and after a rollback.
poll_health() {
    local label="$1"
    for attempt in $(seq 1 20); do
        sleep 1
        if curl -sf http://localhost:8000/health > /dev/null; then
            echo "  ✓ ${label} healthy (${attempt}s)"
            return 0
        fi
    done
    return 1
}

# Roll back to the last known good SHA, re-run any install / rebuild
# steps the original deploy ran (so dependencies and frontend bundle
# match the previous code), restart, and verify health. Returns 0 on
# successful recovery, 1 if recovery itself failed.
rollback() {
    local target="$1"
    echo
    echo "↩ Rolling back to ${target:0:7}..."

    # set -e is suppressed inside functions called from `if` contexts,
    # so we explicitly check each step that can fail. A failed reset or
    # rebuild leaves the system in worse shape than the failed deploy
    # did; abort the rollback path immediately and let the caller exit 2.
    if ! git reset --hard "$target"; then
        echo "✗ git reset --hard failed during rollback"
        return 1
    fi

    # Re-run the same install / rebuild gates. CHANGED is the same diff
    # we used on the forward path, so the affected files are the same
    # set being reverted.
    if echo "$CHANGED" | grep -q "^requirements\.txt$"; then
        echo "→ Reinstalling Python deps (rollback)..."
        if ! ./venv/bin/pip install -r requirements.txt; then
            echo "✗ pip install failed during rollback"
            return 1
        fi
    fi
    if echo "$CHANGED" | grep -qE "^frontend-svelte/(package\.json|package-lock\.json)$"; then
        echo "→ Running npm install (rollback)..."
        if ! (cd frontend-svelte && npm install); then
            echo "✗ npm install failed during rollback"
            return 1
        fi
    fi
    if echo "$CHANGED" | grep -qE "^frontend-svelte/(src|static|package\.json|package-lock\.json)$"; then
        echo "→ Rebuilding frontend (rollback)..."
        if ! (cd frontend-svelte && npm run build); then
            echo "✗ npm run build failed during rollback"
            return 1
        fi
    fi

    echo "→ Restarting home-hub.service (rollback)..."
    if ! systemctl --user restart home-hub.service; then
        echo "✗ systemctl restart failed during rollback"
        return 1
    fi

    if poll_health "Backend (post-rollback)"; then
        # Restart ambient_monitor too if the original deploy did — its
        # source has been reverted along with everything else. A failure
        # here doesn't fail the rollback (no health check on ambient).
        if [[ "$RESTART_AMBIENT" == "1" ]]; then
            echo "→ Restarting home-hub-ambient.service (rollback)..."
            systemctl --user restart home-hub-ambient.service || \
                echo "  (ambient restart failed; main service is still healthy)"
        fi
        if [[ "$RESTART_LATITUDE_STREAMING" == "1" ]]; then
            restart_latitude_streaming "rollback"
        fi
        return 0
    fi

    echo "✗ Rollback health check ALSO failed!"
    systemctl --user status home-hub.service --no-pager | tail -20
    return 1
}

restart_latitude_streaming() {
    local suffix="${1:-}"
    if systemctl --user list-unit-files home-hub-latitude-streaming.service \
            --no-pager | grep -q "home-hub-latitude-streaming.service"; then
        if [[ -n "$suffix" ]]; then
            echo "→ Restarting home-hub-latitude-streaming.service (${suffix})..."
        else
            echo "→ Restarting home-hub-latitude-streaming.service..."
        fi
        systemctl --user restart home-hub-latitude-streaming.service || \
            echo "  (latitude streaming restart failed; main backend is unaffected)"
    else
        echo "  (home-hub-latitude-streaming.service not installed — see deployment/home-hub-latitude-streaming.service)"
    fi
}

install_kiosk_recycle_timer() {
    if [[ ! -f deployment/home-hub-kiosk-recycle.service || ! -f deployment/home-hub-kiosk-recycle.timer ]]; then
        echo "  (kiosk recycle units not present in this checkout; skipping)"
        return 0
    fi

    echo "→ Installing home-hub-kiosk-recycle.timer..."
    mkdir -p "$HOME/.config/systemd/user"
    cp deployment/home-hub-kiosk-recycle.service "$HOME/.config/systemd/user/"
    cp deployment/home-hub-kiosk-recycle.timer "$HOME/.config/systemd/user/"
    chmod +x scripts/recycle-kiosk.sh
    systemctl --user daemon-reload
    systemctl --user enable --now home-hub-kiosk-recycle.timer
}

if [[ "$INSTALL_KIOSK_RECYCLE" == "1" ]]; then
    install_kiosk_recycle_timer
fi
if [[ "$RESTART_BACKEND" == "1" ]]; then
    echo "→ Restarting home-hub.service (systemd --user)..."
    systemctl --user restart home-hub.service
    # FastAPI typically binds in 2-5s but can take longer on first-deploy
    # (cold import tree). Retry for up to 20s.
    if ! poll_health "Backend"; then
        echo "✗ Health check failed after 20s!"
        echo
        systemctl --user status home-hub.service --no-pager | tail -20

        if [[ -n "$LAST_DEPLOYED" ]]; then
            if rollback "$LAST_DEPLOYED"; then
                echo
                echo "↩ Rolled back to ${LAST_DEPLOYED:0:7} (deploy of ${NEW_HEAD:0:7} failed health check)."
                # Marker is unchanged — still points at LAST_DEPLOYED — so
                # the next deploy will diff cleanly from the rollback target.
                exit 1
            fi
            echo
            echo "✗✗ Both deploy AND rollback failed. System is in an inconsistent state."
            echo "    Inspect logs and run 'git status' to recover manually."
            exit 2
        fi

        echo
        echo "(No prior deploy recorded — nothing to roll back to.)"
        exit 1
    fi
fi

if [[ "$RESTART_AMBIENT" == "1" ]]; then
    echo "→ Restarting home-hub-ambient.service..."
    systemctl --user restart home-hub-ambient.service
fi

if [[ "$RESTART_LATITUDE_STREAMING" == "1" ]]; then
    restart_latitude_streaming
fi

if [[ "$RESTART_TUNNEL" == "1" ]]; then
    # Best-effort: home-hub-tunnel.service is a one-time manual install
    # (see deployment/home-hub-tunnel.service). If it isn't installed yet,
    # skip cleanly so deploy doesn't fail on Latitudes pre-Phase 5.
    if systemctl --user list-unit-files home-hub-tunnel.service \
            --no-pager | grep -q "home-hub-tunnel.service"; then
        echo "→ Restarting home-hub-tunnel.service..."
        systemctl --user restart home-hub-tunnel.service || \
            echo "  (tunnel restart failed; main backend is unaffected)"
    else
        echo "  (home-hub-tunnel.service not installed — see deployment/home-hub-tunnel.service)"
    fi
fi

# Record success — only reached if every step above passed (set -e).
echo "$NEW_HEAD" > "$MARKER"

echo
echo "✓ Deploy complete."
