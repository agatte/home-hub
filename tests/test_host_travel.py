from __future__ import annotations

import asyncio
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.api import auth
from backend.api.routes import host
from backend.main import app


def _bash_executable() -> str:
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        if git_bash.exists():
            return str(git_bash)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the hostctl transaction harness")
    return bash


def _bash_path(path: Path) -> str:
    resolved = path.resolve().as_posix()
    if os.name == "nt" and len(resolved) >= 3 and resolved[1:3] == ":/":
        return f"/{resolved[0].lower()}{resolved[2:]}"
    return resolved


def _run_hostctl(tmp_path: Path, scenario: str) -> tuple[subprocess.CompletedProcess, Path, str]:
    home = tmp_path / "home"
    fake_bin = tmp_path / "bin"
    fake_repo = tmp_path / "repo"
    state_dir = home / ".local/state/home-hub"
    state_dir.mkdir(parents=True)
    fake_bin.mkdir()
    (fake_repo / "scripts").mkdir(parents=True)
    (fake_repo / "deployment").mkdir()
    marker_text = "travel-start guest_gateway_active=1\n" if scenario == "success_guest_active" else "travel-start\n"
    (state_dir / "travel-mode").write_text(marker_text, encoding="utf-8")
    event_log = tmp_path / "events.log"

    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text(
        """#!/usr/bin/env bash
printf 'systemctl %s\\n' "$*" >> "$EVENT_LOG"
if [[ "$*" == *"list-unit-files"* ]]; then
  for arg in "$@"; do
    if [[ "$arg" == *.service || "$arg" == *.timer ]]; then
      printf '%s enabled\\n' "$arg"
      break
    fi
  done
elif [[ "$*" == *"is-active"* ]]; then
  printf 'inactive\\n'
fi
""",
        encoding="utf-8",
    )
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
url=""
method="GET"
for arg in "$@"; do
  [[ "$arg" == http://* ]] && url="$arg"
done
[[ "$*" == *"-X POST"* ]] && method="POST"
printf 'curl %s %s\\n' "$method" "$url" >> "$EVENT_LOG"
if [[ "$url" == */activate ]]; then
  if [[ -f "$HOME/.local/state/home-hub/returning-home" ]]; then
    printf 'activate while-returning\\n' >> "$EVENT_LOG"
  else
    printf 'activate after-home\\n' >> "$EVENT_LOG"
  fi
  [[ "$HOSTCTL_SCENARIO" == "activation_fail" ]] && printf '503' || printf '200'
  exit 0
fi
if [[ "$url" == "http://localhost:8000/health" ]]; then
  [[ "$HOSTCTL_SCENARIO" == "backend_fail" ]] && exit 22
  exit 0
fi
if [[ "$method" == "POST" ]]; then
  case "$HOSTCTL_SCENARIO" in
    success|success_guest_active) printf '200' ; exit 0 ;;
    reject) printf '409' ; exit 0 ;;
    timeout_then_committed) exit 28 ;;
    ambiguous) printf '503' ; exit 0 ;;
  esac
fi
case "$HOSTCTL_SCENARIO" in
  timeout_then_committed) printf '200' ;;
  *) printf '409' ;;
esac
""",
        encoding="utf-8",
    )
    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_notify = fake_bin / "notify-send"
    fake_notify.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_recycle = fake_repo / "scripts/recycle-kiosk.sh"
    fake_recycle.write_text(
        """#!/usr/bin/env bash
if [[ -f "$HOME/.local/state/home-hub/returning-home" ]]; then
  printf 'kiosk while-returning\\n' >> "$EVENT_LOG"
else
  printf 'kiosk after-home\\n' >> "$EVENT_LOG"
fi
""",
        encoding="utf-8",
    )
    (fake_repo / "deployment/home-hub-return.desktop").write_text(
        "[Desktop Entry]\nType=Application\n", encoding="utf-8"
    )
    for executable in (fake_systemctl, fake_curl, fake_sleep, fake_notify, fake_recycle):
        executable.chmod(0o755)

    env = os.environ.copy()
    script = _bash_path(host.PROJECT_ROOT / "scripts/homehub-hostctl.sh")
    shell_command = (
        f'export PATH="{_bash_path(fake_bin)}:/usr/bin:/bin"; '
        f'export HOME="{_bash_path(home)}"; '
        f'export HOME_HUB_ROOT="{_bash_path(fake_repo)}"; '
        f'export EVENT_LOG="{_bash_path(event_log)}"; '
        f'export TMPDIR="{_bash_path(tmp_path)}"; '
        f'export HOSTCTL_SCENARIO="{scenario}"; '
        'export DISPLAY=":0"; export WAYLAND_DISPLAY=""; '
        f'"{script}" home --force'
    )
    args = [_bash_executable(), "-c", shell_command]
    stdout_path = tmp_path / "stdout.log"
    stderr_path = tmp_path / "stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr_file:
        completed = subprocess.run(
            args,
            check=False,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            env=env,
            cwd=host.PROJECT_ROOT,
            timeout=20,
        )
    result = subprocess.CompletedProcess(
        args=args,
        returncode=completed.returncode,
        stdout=stdout_path.read_text(encoding="utf-8"),
        stderr=stderr_path.read_text(encoding="utf-8"),
    )
    events = event_log.read_text(encoding="utf-8") if event_log.exists() else ""
    return result, state_dir, events


def _request(hostname: str, *, tunnel: bool = False) -> Request:
    headers = [(b"x-tunnel-origin", b"cloudflare")] if tunnel else []
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/host/travel",
        "headers": headers,
        "client": (hostname, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })


def test_require_localhost_rejects_lan_and_tunnel_loopback():
    asyncio.run(auth.require_localhost(_request("127.0.0.1")))
    with pytest.raises(HTTPException) as lan:
        asyncio.run(auth.require_localhost(_request("192.168.86.30")))
    assert lan.value.status_code == 403
    with pytest.raises(HTTPException) as tunnel:
        asyncio.run(auth.require_localhost(_request("127.0.0.1", tunnel=True)))
    assert tunnel.value.status_code == 403


def test_host_status_reads_persistent_marker(monkeypatch, tmp_path: Path):
    marker = tmp_path / "travel-mode"
    returning = tmp_path / "returning-home"
    monkeypatch.setattr(host, "STATE_FILE", marker)
    monkeypatch.setattr(host, "RETURNING_HOME_STATE_FILE", returning)
    with TestClient(app) as client:
        response = client.get("/api/host/status")
        assert response.status_code == 200
        assert response.json()["mode"] == "HOME"

        marker.write_text("2026-09-02T13:00:00-04:00 source=test\n", encoding="utf-8")
        response = client.get("/api/host/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "TRAVEL"
        assert payload["travel_marker"] is True
        assert "2026-09-02" in payload["entered_at"]

        returning.write_text("return transaction\n", encoding="utf-8")
        response = client.get("/api/host/status")
        payload = response.json()
        assert payload["mode"] == "RETURNING_HOME"
        assert payload["returning_home_marker"] is True
        # Transitional truth wins even if interruption left both markers.
        assert payload["travel_marker"] is True
        assert payload["entered_at"] == "return transaction"


def test_enter_travel_acknowledges_before_detached_shutdown(monkeypatch, tmp_path: Path):
    marker = tmp_path / "travel-mode"
    monkeypatch.setattr(host, "STATE_FILE", marker)
    monkeypatch.setattr(host, "_schedule_travel", lambda delay_seconds=1.5: "travel-test.service")

    invalidated = []
    fake_presence = SimpleNamespace(invalidate_source=lambda source: invalidated.append(source))
    with TestClient(app) as client:
        app.state.presence = fake_presence
        app.state.away_manager = None
        response = client.post("/api/host/travel")
    assert response.status_code == 200
    assert invalidated == ["latitude"]
    payload = response.json()
    assert payload["status"] == "arming"
    assert payload["mode"] == "TRAVEL"
    assert payload["helper_unit"] == "travel-test.service"
    assert "DNS" in payload["dns_warning"]


def test_schedule_travel_uses_detached_user_systemd(monkeypatch, tmp_path: Path):
    helper = tmp_path / "homehub-hostctl.sh"
    helper.write_text("#!/bin/bash\n", encoding="utf-8")
    monkeypatch.setattr(host, "HOSTCTL", helper)
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(host.subprocess, "run", fake_run)
    unit = host._schedule_travel(2.0)
    command = seen["command"]
    assert command[:2] == ["systemd-run", "--user"]
    assert "--collect" in command
    assert "--no-block" in command
    assert str(helper) in command
    assert command[-4:] == [str(helper), "travel", "--delay", "2.0"]
    assert unit.startswith("home-hub-travel-enter-")


def test_hostctl_contract_keeps_ambient_parked_and_dns_out_of_scope():
    script = (host.PROJECT_ROOT / "scripts" / "homehub-hostctl.sh").read_text(encoding="utf-8")
    assert "disable --now" in script
    assert "home-hub-latitude-streaming.service" in script
    assert "home-hub-tunnel.service" in script
    assert "home-hub-guest-gateway.service" in script
    assert "home-hub-kiosk-recycle.timer" in script
    assert "home-hub-ambient.service" in script
    assert "SUPPRESSED_UNITS" in script
    assert "enable --now home-hub-ambient.service" not in script
    assert "RETURN_UNITS=(" in script
    return_units = script.split("RETURN_UNITS=(", 1)[1].split(")", 1)[0]
    assert "home-hub-ambient.service" not in return_units
    assert "home-hub-guest-gateway.service" not in return_units
    suppressed_units = script.split("SUPPRESSED_UNITS=(", 1)[1].split(")", 1)[0]
    assert "home-hub-guest-gateway.service" in suppressed_units
    assert "guest_gateway_active=1" in script
    assert 'if [[ "$restore_guest_gateway" == "1" ]]' in script
    assert 'mv "$MARKER" "$RETURNING_MARKER"' in script
    assert "ensure_reconciliation_id" in script
    assert "reconciliation_id=" in script
    return_home = script.split("return_home() {", 1)[1].split("show_status() {", 1)[0]
    assert return_home.index("ensure_reconciliation_id") < return_home.index("enable_start_if_known")
    assert return_home.index("activate_home_authority") < return_home.index('rm -f "$RETURNING_MARKER"')
    assert return_home.index('rm -f "$RETURNING_MARKER"') < return_home.index('for unit in "${RETURN_UNITS[@]}"')
    assert "docker compose stop" not in script
    assert "Google/Nest Wifi DNS failover is not changed" in script


def test_systemd_home_units_respect_travel_marker():
    condition = "ConditionPathExists=!%h/.local/state/home-hub/travel-mode"
    returning_condition = "ConditionPathExists=!%h/.local/state/home-hub/returning-home"
    units = [
        "home-hub.service", "home-hub-tunnel.service",
        "home-hub-guest-gateway.service",
        "home-hub-latitude-streaming.service", "home-hub-ambient.service",
        "home-hub-kiosk-recycle.service", "home-hub-kiosk-recycle.timer",
    ]
    for unit in units:
        body = (host.PROJECT_ROOT / "deployment" / unit).read_text(encoding="utf-8")
        assert condition in body
        if unit != "home-hub.service":
            assert returning_condition in body


def test_deploy_respects_host_lifecycle_markers():
    script = (host.PROJECT_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")
    assert 'TRAVEL_MARKER="$HOME/.local/state/home-hub/travel-mode"' in script
    assert 'RETURNING_HOME_MARKER="$HOME/.local/state/home-hub/returning-home"' in script
    assert "Travel Mode is active" in script
    assert "refusing deploy/restart in RETURNING_HOME" in script
    assert "RESTART_GUEST_GATEWAY" in script
    assert "home-hub-guest-gateway.service" in script
    assert "restart_guest_gateway" in script


def test_returning_home_bootstrap_holds_automation_until_reconciled():
    bootstrap = (host.PROJECT_ROOT / "backend" / "bootstrap.py").read_text(
        encoding="utf-8"
    )
    assert '"home-hub" / "returning-home"' in bootstrap
    assert 'automation.arm_host_return_suppression("host:returning-home")' in bootstrap


def test_travel_helper_is_armed_before_graceful_departure(monkeypatch, tmp_path: Path):
    marker = tmp_path / "travel-mode"
    monkeypatch.setattr(host, "STATE_FILE", marker)
    events = []
    monkeypatch.setattr(host, "_schedule_travel", lambda delay_seconds=5.0: events.append("armed") or "travel-test.service")

    class FakeAway:
        async def handle_event(self, event, source):
            events.append("away")
            return "ok"

    with TestClient(app) as client:
        app.state.away_manager = FakeAway()
        app.state.presence = SimpleNamespace(invalidate_source=lambda source: events.append("invalidate"))
        response = client.post("/api/host/travel")
    assert response.status_code == 200
    assert events[0] == "armed"
    assert events.index("armed") < events.index("away")


@pytest.mark.skipif(os.name == "nt", reason="Git Bash teardown is nondeterministic on Windows; run on Linux runtime/CI")
def test_return_home_restores_guest_gateway_only_when_previously_active(tmp_path: Path):
    result, _, events = _run_hostctl(tmp_path / "inactive", "success")
    assert result.returncode == 0, result.stderr
    assert "enable --now home-hub-guest-gateway.service" not in events

    result, _, events = _run_hostctl(tmp_path / "active", "success_guest_active")
    assert result.returncode == 0, result.stderr
    assert "enable --now home-hub-guest-gateway.service" in events


def test_return_home_success_orders_commit_before_units_and_kiosk(tmp_path: Path):
    result, state_dir, events = _run_hostctl(tmp_path, "success")

    assert result.returncode == 0, result.stderr
    assert not (state_dir / "travel-mode").exists()
    assert not (state_dir / "returning-home").exists()
    assert events.index("enable --now home-hub.service") < events.index(
        "curl POST http://localhost:8000/api/presence/reconcile-home"
    )
    committed = events.index("curl POST http://localhost:8000/api/presence/reconcile-home")
    activated = events.index("activate while-returning")
    assert committed < activated < events.index("enable --now home-hub-tunnel.service")
    assert committed < events.index("enable --now home-hub-latitude-streaming.service")
    assert committed < events.index("enable --now home-hub-kiosk-recycle.timer")
    assert "activate while-returning" in events
    assert "activate after-home" not in events
    assert "kiosk after-home" in events
    assert "enable --now home-hub-ambient.service" not in events
    assert "HomeHub host mode: HOME" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="Git Bash teardown is nondeterministic on Windows; run on Linux runtime/CI")
def test_return_home_resolves_timeout_using_transaction_status(tmp_path: Path):
    result, state_dir, events = _run_hostctl(tmp_path, "timeout_then_committed")

    assert result.returncode == 0, result.stderr
    assert events.splitlines().count("curl POST http://localhost:8000/api/presence/reconcile-home") == 3
    assert "curl GET http://localhost:8000/api/presence/reconcile-home/return-" in events
    assert "enable --now home-hub-tunnel.service" in events
    assert not (state_dir / "returning-home").exists()


@pytest.mark.skipif(os.name == "nt", reason="Git Bash teardown is nondeterministic on Windows; run on Linux runtime/CI")
def test_definitive_reconciliation_failure_rolls_back_to_travel(tmp_path: Path):
    result, state_dir, events = _run_hostctl(tmp_path, "reject")

    assert result.returncode == 1
    assert (state_dir / "travel-mode").read_text(encoding="utf-8") == "travel-start\n"
    assert not (state_dir / "returning-home").exists()
    assert "disable --now home-hub.service" in events
    assert "enable --now home-hub-tunnel.service" not in events
    assert "kiosk" not in events


@pytest.mark.skipif(os.name == "nt", reason="Git Bash teardown is nondeterministic on Windows; run on Linux runtime/CI")
def test_ambiguous_reconciliation_preserves_returning_home(tmp_path: Path):
    result, state_dir, events = _run_hostctl(tmp_path, "ambiguous")

    assert result.returncode == 2
    assert not (state_dir / "travel-mode").exists()
    returning = (state_dir / "returning-home").read_text(encoding="utf-8")
    assert returning.startswith("travel-start")
    assert "reconciliation_id=return-" in returning
    assert "disable --now home-hub.service" not in events
    assert "enable --now home-hub-tunnel.service" not in events
    assert "kiosk" not in events
    assert "mode remains RETURNING_HOME" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Git Bash teardown is nondeterministic on Windows; run on Linux runtime/CI")
def test_backend_start_failure_rolls_back_before_reconciliation(tmp_path: Path):
    result, state_dir, events = _run_hostctl(tmp_path, "backend_fail")

    assert result.returncode == 1
    assert (state_dir / "travel-mode").exists()
    assert not (state_dir / "returning-home").exists()
    assert "curl POST" not in events
    assert "disable --now home-hub.service" in events
