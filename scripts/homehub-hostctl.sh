#!/usr/bin/env bash
# HomeHub portable-Latitude host control.  This is intentionally independent
# of FastAPI so Return Home still works while the backend is stopped.
set -euo pipefail

ACTION="${1:-status}"
shift || true
DELAY_SECONDS=0
FORCE_HOME=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --delay) DELAY_SECONDS="${2:?missing delay}"; shift 2 ;;
        --force) FORCE_HOME=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

STATE_DIR="$HOME/.local/state/home-hub"
MARKER="$STATE_DIR/travel-mode"
RETURNING_MARKER="$STATE_DIR/returning-home"
RECONCILIATION_ID=""
REPO="${HOME_HUB_ROOT:-$HOME/home-hub}"
AUTOSTART="$HOME/.config/autostart/home-hub-kiosk.desktop"
AUTOSTART_DISABLED="${AUTOSTART}.disabled"
RETURN_DESKTOP="$HOME/.local/share/applications/home-hub-return.desktop"

CORE_SERVICE="home-hub.service"
RETURN_UNITS=(
    home-hub-tunnel.service
    home-hub-latitude-streaming.service
    home-hub-kiosk-recycle.timer
)
SUPPRESSED_UNITS=(
    "${RETURN_UNITS[@]}"
    home-hub-ambient.service
)

unit_known() {
    systemctl --user list-unit-files "$1" --no-pager 2>/dev/null | grep -q "^$1"
}

stop_disable_if_known() {
    local unit="$1"
    if unit_known "$unit"; then
        systemctl --user disable --now "$unit"
    fi
}

enable_start_if_known() {
    local unit="$1"
    if unit_known "$unit"; then
        systemctl --user enable --now "$unit"
    fi
}

install_return_launcher() {
    local source="$REPO/deployment/home-hub-return.desktop"
    if [[ -f "$source" ]]; then
        mkdir -p "$(dirname "$RETURN_DESKTOP")"
        cp "$source" "$RETURN_DESKTOP"
        chmod 0644 "$RETURN_DESKTOP"
    fi
}

suppress_kiosk() {
    if [[ -f "$AUTOSTART" ]]; then
        mv "$AUTOSTART" "$AUTOSTART_DISABLED"
    fi
    pkill -TERM -u "$USER" -f 'firefox.*--kiosk[[:space:]]+http://localhost:8000' 2>/dev/null || true
}

restore_kiosk() {
    if [[ -f "$AUTOSTART_DISABLED" && ! -f "$AUTOSTART" ]]; then
        mv "$AUTOSTART_DISABLED" "$AUTOSTART"
    fi
    if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" && -x "$REPO/scripts/recycle-kiosk.sh" ]]; then
        "$REPO/scripts/recycle-kiosk.sh" >/tmp/home-hub-return-kiosk.log 2>&1 || true
    fi
}

on_home_network() {
    ip -4 addr show 2>/dev/null | grep -Eq 'inet[[:space:]]+192\.168\.86\.[0-9]+/'
}

notify() {
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "HomeHub" "$1" >/dev/null 2>&1 || true
    fi
}

write_marker() {
    mkdir -p "$STATE_DIR"
    local tmp="$MARKER.tmp.$$"
    printf '%s source=local-hostctl\n' "$(date --iso-8601=seconds)" > "$tmp"
    mv "$tmp" "$MARKER"
}

begin_return_home() {
    mkdir -p "$STATE_DIR"
    if [[ -f "$RETURNING_MARKER" ]]; then
        # Resume an interrupted transaction. A stale Travel marker would keep
        # the core blocked, while RETURNING_HOME already preserves safe status.
        rm -f "$MARKER"
        return
    fi
    if [[ -f "$MARKER" ]]; then
        # Same-filesystem rename: there is no crash-persistent markerless state.
        mv "$MARKER" "$RETURNING_MARKER"
        return
    fi
    local tmp="$RETURNING_MARKER.tmp.$$"
    printf '%s source=local-hostctl\n' "$(date --iso-8601=seconds)" > "$tmp"
    mv "$tmp" "$RETURNING_MARKER"
}

ensure_reconciliation_id() {
    RECONCILIATION_ID="$(sed -n 's/.*reconciliation_id=\([A-Za-z0-9._:-]*\).*/\1/p' "$RETURNING_MARKER" | head -n 1)"
    if [[ -n "$RECONCILIATION_ID" ]]; then
        return 0
    fi
    RECONCILIATION_ID="return-$(date +%s)-$$"
    local tmp="$RETURNING_MARKER.id.$$"
    awk -v id="$RECONCILIATION_ID" '
        NR == 1 { print $0 " reconciliation_id=" id; next }
        { print }
    ' "$RETURNING_MARKER" > "$tmp"
    mv "$tmp" "$RETURNING_MARKER"
}

rollback_return_home() {
    if [[ -f "$RETURNING_MARKER" ]]; then
        local tmp="$RETURNING_MARKER.rollback.$$"
        sed -E 's/[[:space:]]+reconciliation_id=[^[:space:]]+//' "$RETURNING_MARKER" > "$tmp"
        mv "$tmp" "$RETURNING_MARKER"
        mv "$RETURNING_MARKER" "$MARKER"
    elif [[ ! -f "$MARKER" ]]; then
        write_marker
    fi
    stop_disable_if_known "$CORE_SERVICE" || true
}

wait_for_backend() {
    for _ in $(seq 1 30); do
        if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

reconcile_home_authority() {
    local response_file
    response_file="$(mktemp "${TMPDIR:-/tmp}/home-hub-reconcile.XXXXXX")" || return 11
    local payload="{\"reconciliation_id\":\"$RECONCILIATION_ID\"}"
    local http_code=""

    for _ in $(seq 1 3); do
        http_code=""
        if http_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
            --connect-timeout 2 --max-time 5 \
            -H 'Content-Type: application/json' \
            -H 'X-Source: return_home:hostctl' \
            -X POST http://localhost:8000/api/presence/reconcile-home \
            --data "$payload")"; then
            if [[ "$http_code" == "200" ]]; then
                rm -f "$response_file"
                return 0
            fi
            if [[ "$http_code" == "409" ]]; then
                rm -f "$response_file"
                return 10
            fi
        fi
        sleep 1
    done

    # A disconnect may happen after SQLite committed. Resolve only positive,
    # transaction-tagged proof; every other result remains indeterminate.
    http_code=""
    if http_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
        --connect-timeout 2 --max-time 5 \
        "http://localhost:8000/api/presence/reconcile-home/$RECONCILIATION_ID")" \
        && [[ "$http_code" == "200" ]]; then
        rm -f "$response_file"
        return 0
    fi
    rm -f "$response_file"
    return 11
}

activate_home_authority() {
    local response_file
    response_file="$(mktemp "${TMPDIR:-/tmp}/home-hub-activate.XXXXXX")" || return 1
    local http_code=""
    for _ in $(seq 1 3); do
        http_code=""
        if http_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
            --connect-timeout 2 --max-time 5 \
            -H 'X-Source: return_home:hostctl' \
            -X POST "http://localhost:8000/api/presence/reconcile-home/$RECONCILIATION_ID/activate")" \
            && [[ "$http_code" == "200" ]]; then
            rm -f "$response_file"
            return 0
        fi
        sleep 1
    done
    rm -f "$response_file"
    return 1
}

enter_travel() {
    if [[ "$DELAY_SECONDS" != "0" ]]; then
        sleep "$DELAY_SECONDS"
    fi
    write_marker
    rm -f "$RETURNING_MARKER"
    install_return_launcher

    local degraded=()
    for unit in "${SUPPRESSED_UNITS[@]}"; do
        if ! stop_disable_if_known "$unit"; then
            degraded+=("$unit")
        fi
    done
    suppress_kiosk
    if ! stop_disable_if_known "$CORE_SERVICE"; then
        degraded+=("$CORE_SERVICE")
    fi
    echo "HomeHub host mode: TRAVEL"
    echo "Google/Nest Wifi DNS failover is not changed by this command."
    if [[ ${#degraded[@]} -gt 0 ]]; then
        notify "Travel Mode armed with degraded stops: ${degraded[*]}"
        echo "Degraded stops: ${degraded[*]}" >&2
    fi
}

return_home() {
    if [[ "$FORCE_HOME" != "1" ]] && ! on_home_network; then
        notify "Return Home blocked: apartment network not detected."
        echo "Apartment network (192.168.86.0/24) not detected." >&2
        echo "Use the terminal override only if you are actually home." >&2
        exit 3
    fi

    begin_return_home
    ensure_reconciliation_id
    if ! enable_start_if_known "$CORE_SERVICE" || ! wait_for_backend; then
        rollback_return_home
        notify "Return Home failed; Travel Mode remains armed."
        echo "Backend failed to become healthy; Travel Mode remains armed." >&2
        exit 1
    fi

    local reconcile_rc=0
    if reconcile_home_authority; then
        reconcile_rc=0
    else
        reconcile_rc=$?
    fi
    if [[ "$reconcile_rc" == "10" ]]; then
        rollback_return_home
        notify "Return Home rejected; Travel Mode remains armed."
        echo "Home occupancy did not commit; Travel Mode remains armed." >&2
        exit 1
    fi
    if [[ "$reconcile_rc" != "0" ]]; then
        notify "Return Home is indeterminate; retry while at home."
        echo "Home occupancy outcome is indeterminate; mode remains RETURNING_HOME." >&2
        exit 2
    fi

    # Activate while RETURNING_HOME is still durable. Any interruption before
    # marker removal therefore remains conservative and is safely retryable.
    if ! activate_home_authority; then
        notify "Return Home activation is indeterminate; retry while at home."
        echo "Occupancy activation is indeterminate; mode remains RETURNING_HOME." >&2
        exit 2
    fi

    # Activation succeeded for the same durable transaction. Publishing HOME is
    # now a single marker removal; dependent units remain held until after it.
    rm -f "$RETURNING_MARKER"

    local degraded=()
    for unit in "${RETURN_UNITS[@]}"; do
        if ! enable_start_if_known "$unit"; then
            degraded+=("$unit")
        fi
    done

    restore_kiosk
    if [[ ${#degraded[@]} -gt 0 ]]; then
        notify "HomeHub is HOME; degraded: ${degraded[*]}"
        echo "HomeHub host mode: HOME (degraded: ${degraded[*]})"
    else
        notify "HomeHub is HOME and the backend is healthy."
        echo "HomeHub host mode: HOME"
    fi
}

show_status() {
    if [[ -f "$RETURNING_MARKER" ]]; then
        echo "HomeHub host mode: RETURNING_HOME"
        cat "$RETURNING_MARKER"
    elif [[ -f "$MARKER" ]]; then
        echo "HomeHub host mode: TRAVEL"
        cat "$MARKER"
    else
        echo "HomeHub host mode: HOME"
    fi
    for unit in "$CORE_SERVICE" "${SUPPRESSED_UNITS[@]}"; do
        if unit_known "$unit"; then
            printf '%-42s %s\n' "$unit" "$(systemctl --user is-active "$unit" 2>/dev/null || true)"
        fi
    done
}

case "$ACTION" in
    travel) enter_travel ;;
    home) return_home ;;
    status) show_status ;;
    *) echo "Usage: $0 {travel|home|status} [--delay SECONDS] [--force]" >&2; exit 2 ;;
esac
