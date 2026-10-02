"""Navigation-v1 child entrypoint for the enforced Windows replay sandbox."""

from __future__ import annotations

import asyncio
import json
import msvcrt
import os
import socket
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

RESULT_SCHEMA_ID = "homehub.replay.navigation.result.v1"
MAX_NETWORK_PROBE_SECONDS = 0.25
FORBIDDEN_PRODUCTION_PATHS = (
    Path(r"C:\Work\home-hub-project\main\.env"),
    Path(r"C:\Users\Anthony\Documents\home-hub-project\main\.env"),
    Path(r"C:\HostBridge\status.json"),
    Path(r"C:\HostBridgeRequests"),
    Path(r"C:\HostBridgeResponses"),
)


def _write_result(handle_value: int, payload: dict[str, Any]) -> None:
    fd = msvcrt.open_osfhandle(handle_value, os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()


def _timedelta_ns(value) -> int:
    return (value.days * 86_400 + value.seconds) * 1_000_000_000 + value.microseconds * 1_000


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _json_light_stamps(values: dict[str, datetime]) -> dict[str, str]:
    return {key: _iso(value) for key, value in sorted(values.items())}


def _expect_denied(label: str, operation) -> dict[str, str]:
    try:
        operation()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return {
            "label": label,
            "status": "denied",
            "error": type(exc).__name__,
        }
    raise RuntimeError(f"isolation self-test failed: {label} unexpectedly succeeded")


def _network_probe() -> None:
    sock = socket.socket()
    try:
        sock.settimeout(MAX_NETWORK_PROBE_SECONDS)
        result = sock.connect_ex(("198.51.100.1", 9))
        if result == 0:
            raise RuntimeError("sandbox unexpectedly reached TEST-NET endpoint")
        raise OSError(result, "network connection unavailable")
    finally:
        sock.close()


def _run_isolation_self_test(bundle_dir: Path) -> dict[str, Any]:
    checks = []
    for path in FORBIDDEN_PRODUCTION_PATHS:
        checks.append(
            _expect_denied(
                f"production_path:{path}",
                lambda target=path: target.open("rb").read(1),
            )
        )

    manifest = bundle_dir / "manifest.json"
    checks.append(
        _expect_denied(
            "bundle_is_read_only",
            lambda: manifest.open("ab").write(b"x"),
        )
    )
    checks.append(
        _expect_denied(
            "child_process_creation",
            lambda: subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", "pass"],
                check=False,
                timeout=2,
            ),
        )
    )
    checks.append(_expect_denied("network", _network_probe))
    return {"status": "passed", "checks": checks}


async def _run(bundle_dir: Path) -> dict[str, Any]:
    stage_root = bundle_dir.parent
    deps = stage_root / "deps"
    project = stage_root / "project"
    sys.path[:0] = [str(project), str(deps)]

    from backend.replay.clock import parse_utc
    from backend.replay.navigation_v1 import NavigationV1Replay
    from backend.replay.validate import load_fixture_bundle

    bundle = load_fixture_bundle(bundle_dir)
    root = NavigationV1Replay.from_bundle(bundle)

    end_utc = parse_utc(bundle.manifest.window.end_utc, "window.end_utc")
    anchor_utc = parse_utc(
        bundle.manifest.time.wall_time_anchor_utc,
        "wall_time_anchor_utc",
    )
    end_mono_ns = bundle.manifest.time.backend_monotonic_origin_ns + _timedelta_ns(
        end_utc - anchor_utc
    )
    await root.run_until(end_mono_ns)

    house_state, activity, effective_mode = root.authority._project_authority()
    return {
        "schema_id": RESULT_SCHEMA_ID,
        "status": "ok",
        "bundle_id": bundle.manifest.bundle_id,
        "isolation_self_test": _run_isolation_self_test(bundle_dir),
        "clock": {
            "monotonic_ns": root.clock.monotonic_ns(),
            "utc": _iso(root.clock.utc_now()),
        },
        "authority": {
            "current_mode": root.authority.current_mode,
            "house_state": house_state,
            "activity": activity,
            "effective_mode": effective_mode,
        },
        "transit": {
            "active": root.transit.active,
            "owned_lights": sorted(root.transit._owned_lights),
            "presence_armed": root.transit._presence_armed,
            "strong_absent_streak": root.transit._strong_absent_streak,
            "last_block_reason": root.transit._last_block_reason,
        },
        "engine_state": {
            "manual_light_overrides": _json_light_stamps(root.state.manual_light_overrides),
            "manual_light_targets": root.state.manual_light_targets,
            "transit_light_overrides": _json_light_stamps(root.state.transit_light_overrides),
            "transit_light_targets": root.state.transit_light_targets,
            "last_applied_per_light": root.state.last_applied_per_light,
        },
        "light_requests": [asdict(request) for request in root.sink.requests],
        "event_sink": {
            "light_adjustments": root.events.light_adjustments,
            "learner_decisions": root.events.learner_decisions,
        },
    }


def main() -> int:
    if len(sys.argv) != 3:
        return 64
    try:
        handle_value = int(sys.argv[1])
    except ValueError:
        return 64

    bundle_dir = Path(sys.argv[2])
    safe_env = {
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }
    os.environ.clear()
    os.environ.update(safe_env)

    try:
        payload = asyncio.run(_run(bundle_dir))
        exit_code = 0
    except BaseException as exc:
        payload = {
            "schema_id": RESULT_SCHEMA_ID,
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
        }
        exit_code = 2

    try:
        _write_result(handle_value, payload)
    except BaseException:
        return 70
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
