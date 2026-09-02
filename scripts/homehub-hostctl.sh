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

wait_for_backend() {
    for _ in $(seq 1 30); do
        if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

enter_travel() {
    if [[ "$DELAY_SECONDS" != "0" ]]; then
        sleep "$DELAY_SECONDS"
    fi
    write_marker
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

    local prior_marker=""
    prior_marker="$(cat "$MARKER" 2>/dev/null || true)"
    rm -f "$MARKER"
    if ! enable_start_if_known "$CORE_SERVICE" || ! wait_for_backend; then
        mkdir -p "$STATE_DIR"
        if [[ -n "$prior_marker" ]]; then
            printf '%s\n' "$prior_marker" > "$MARKER"
        else
            write_marker
        fi
        stop_disable_if_known "$CORE_SERVICE"
        notify "Return Home failed; Travel Mode remains armed."
        echo "Backend failed to become healthy; Travel Mode remains armed." >&2
        exit 1
    fi

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
    if [[ -f "$MARKER" ]]; then
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
