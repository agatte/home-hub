#!/usr/bin/env bash
#
# Recycle the Latitude Firefox kiosk without restarting Home Hub.
#
# The scheduled timer runs this weekly after the ML nightly window. It targets
# only the Firefox process that was launched with the kiosk URL, so Stremio or
# any other media app can remain open without being killed.

set -euo pipefail

KIOSK_URL="${KIOSK_URL:-http://localhost:8000}"
FIREFOX_BIN="${FIREFOX_BIN:-firefox}"
SWAP_THRESHOLD_KB="${KIOSK_RECYCLE_SWAP_THRESHOLD_KB:-1048576}"
MAX_AGE_SECONDS="${KIOSK_RECYCLE_MAX_AGE_SECONDS:-604800}"
GRACE_SECONDS="${KIOSK_RECYCLE_GRACE_SECONDS:-20}"
LOG_FILE="${KIOSK_RECYCLE_LOG_FILE:-/tmp/home-hub-kiosk.log}"

uid="$(id -u)"

mapfile -t kiosk_pids < <(
    pgrep -u "$uid" -f "firefox.*--kiosk[[:space:]]+${KIOSK_URL}" || true
)

pid_exists() {
    local pid="$1"
    [[ -d "/proc/$pid" ]]
}

process_age_seconds() {
    local pid="$1"
    local start_ticks uptime_seconds hz start_seconds

    start_ticks="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || echo 0)"
    uptime_seconds="$(awk '{print int($1)}' /proc/uptime)"
    hz="$(getconf CLK_TCK)"
    start_seconds=$((start_ticks / hz))
    echo $((uptime_seconds - start_seconds))
}

process_swap_kb() {
    local pid="$1"
    awk '/^VmSwap:/ {print $2; found=1} END {if (!found) print 0}' \
        "/proc/$pid/status" 2>/dev/null || echo 0
}

launch_kiosk() {
    echo "Launching Firefox kiosk: $KIOSK_URL"
    if command -v systemd-run >/dev/null 2>&1 && [[ -n "${INVOCATION_ID:-}" ]]; then
        systemd-run --user \
            --unit="home-hub-kiosk-browser-${EPOCHSECONDS:-$(date +%s)}" \
            --collect \
            --same-dir \
            --setenv="DISPLAY=${DISPLAY:-:0}" \
            --setenv="WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}" \
            --setenv="XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
            --setenv="DBUS_SESSION_BUS_ADDRESS=${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$(id -u)/bus}" \
            "$FIREFOX_BIN" --kiosk "$KIOSK_URL"
        return
    fi

    nohup "$FIREFOX_BIN" --kiosk "$KIOSK_URL" >>"$LOG_FILE" 2>&1 &
}

restart_kiosk() {
    local pids=("$@")

    echo "Restarting Firefox kiosk pids: ${pids[*]}"
    kill -TERM "${pids[@]}" 2>/dev/null || true

    local deadline=$((SECONDS + GRACE_SECONDS))
    while (( SECONDS < deadline )); do
        local remaining=0
        for pid in "${pids[@]}"; do
            if pid_exists "$pid"; then
                remaining=1
                break
            fi
        done
        [[ "$remaining" == "0" ]] && break
        sleep 1
    done

    for pid in "${pids[@]}"; do
        if pid_exists "$pid"; then
            echo "Kiosk pid $pid ignored TERM; sending KILL"
            kill -KILL "$pid" 2>/dev/null || true
        fi
    done

    sleep 2
    launch_kiosk
}

if [[ "${#kiosk_pids[@]}" == "0" ]]; then
    echo "No Firefox kiosk process found."
    launch_kiosk
    exit 0
fi

total_swap_kb=0
oldest_age_seconds=0
for pid in "${kiosk_pids[@]}"; do
    if ! pid_exists "$pid"; then
        continue
    fi
    swap_kb="$(process_swap_kb "$pid")"
    age_seconds="$(process_age_seconds "$pid")"
    total_swap_kb=$((total_swap_kb + swap_kb))
    if (( age_seconds > oldest_age_seconds )); then
        oldest_age_seconds="$age_seconds"
    fi
done

echo "Firefox kiosk swap=${total_swap_kb}KiB oldest_age=${oldest_age_seconds}s pids=${kiosk_pids[*]}"

if (( SWAP_THRESHOLD_KB > 0 && total_swap_kb >= SWAP_THRESHOLD_KB )); then
    restart_kiosk "${kiosk_pids[@]}"
    exit 0
fi

if (( MAX_AGE_SECONDS > 0 && oldest_age_seconds >= MAX_AGE_SECONDS )); then
    restart_kiosk "${kiosk_pids[@]}"
    exit 0
fi

echo "Kiosk below recycle thresholds; leaving it running."
