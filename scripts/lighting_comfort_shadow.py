"""Operator-invoked one-shot lighting shadow audit. NEVER sends device writes.

Examples:
  python scripts/lighting_comfort_shadow.py --matrix
  python scripts/lighting_comfort_shadow.py --snapshot sample.json
  python scripts/lighting_comfort_shadow.py --base-url http://192.168.86.210:8000

No loop, disk history, or runtime caller. Print whitelisted output only.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services.lighting_comfort_shadow import (  # noqa: E402
    audit_authored_matrix,
    audit_snapshot,
)

ENDPOINTS = {
    "automation_status": "/api/automation/status",
    "automation_pipeline": "/api/automation/pipeline",
    "screen_sync_status": "/api/automation/screen-sync/status",
    "camera_status": "/api/camera/status",
    "bedroom_lux": "/api/camera/desktop/lux",
    "lights": "/api/lights",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not parsed.hostname
    ):
        raise ValueError("base URL must be a credential-free, plain HTTP LAN origin")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        allowed = (
            ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"),
            ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("127.0.0.0/8"),
        )
        if not isinstance(ip, ipaddress.IPv4Address) or not any(
            ip in network for network in allowed
        ):
            raise ValueError("target must be a numeric private/LAN IPv4 address")
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("target must be a numeric private/LAN IP with valid port") from exc
    return base_url.rstrip("/")


def read_only_snapshot(base_url: str) -> tuple[dict, list[dict]]:
    """Only six fixed GETs; never retries, redirects, writes or stores responses."""
    root = validate_base_url(base_url)
    data = {}
    failures = []
    # Never send LAN telemetry to a process-configured HTTP proxy.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    for key, path in ENDPOINTS.items():
        try:
            request = Request(root + path, method="GET", headers={"Accept": "application/json"})
            with opener.open(request, timeout=3) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError("oversized response")
                data[key] = json.loads(raw)
        except (HTTPError, URLError, TimeoutError, ValueError, OSError, UnicodeError) as exc:
            # Never output exception message or raw URLs: may contain private data.
            failures.append({"source": key, "error_type": type(exc).__name__})
    return data, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--matrix", action="store_true", help="offline canonical table screening")
    source.add_argument("--snapshot", type=Path, help="operator-provided JSON API snapshot")
    source.add_argument("--base-url", help="opt-in one-shot, read-only LAN GET collection")
    args = parser.parse_args(argv)
    if args.matrix:
        report = audit_authored_matrix()
    elif args.snapshot is not None:
        with args.snapshot.open(encoding="utf-8") as handle:
            report = audit_snapshot(json.load(handle))
    else:
        try:
            source_data, errors = read_only_snapshot(args.base_url)
        except ValueError as exc:
            parser.error(str(exc))
        report = audit_snapshot(source_data)
        report["source_failures"] = errors
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
