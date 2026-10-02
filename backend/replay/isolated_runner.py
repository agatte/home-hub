"""Operational navigation-v1 isolation contract and backend selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ReplayIsolationUnavailable(RuntimeError):
    """The reviewed operational isolation backend cannot run here."""


@dataclass(frozen=True)
class ReplayIsolationContract:
    no_network: bool = True
    no_device_access: bool = True
    no_subprocess_or_exec: bool = True
    immutable_code_and_input: bool = True
    no_production_filesystem: bool = True
    no_home_env_or_credentials: bool = True
    preopened_result_stream_only: bool = True


REQUIRED_ISOLATION = ReplayIsolationContract()
WINDOWS_SANDBOX_BACKEND = "windows-sandbox-appcontainer-v1"


def supported_isolation_backend() -> str | None:
    """Return the reviewed backend only when its host prerequisites are present."""

    try:
        from .windows_sandbox_runner import backend_available
    except (ImportError, OSError):
        return None
    return WINDOWS_SANDBOX_BACKEND if backend_available() else None


def require_supported_isolation() -> str:
    backend = supported_isolation_backend()
    if backend is None:
        raise ReplayIsolationUnavailable(
            "navigation-v1 operational replay requires a Windows 11 24H2+ "
            "host with the Windows Sandbox CLI. Nested execution from the "
            "normal RDC Windows Sandbox is intentionally unsupported."
        )
    return backend


def run_navigation_v1_isolated(*, bundle_path: str | Path) -> dict[str, Any]:
    """Run a validated bundle in the reviewed transient Windows Sandbox backend."""

    backend = require_supported_isolation()
    if backend != WINDOWS_SANDBOX_BACKEND:
        raise ReplayIsolationUnavailable(f"unsupported replay isolation backend {backend}")

    from .windows_sandbox_runner import (
        WindowsSandboxReplayError,
        run_windows_sandbox_replay,
    )

    try:
        return run_windows_sandbox_replay(bundle_path)
    except WindowsSandboxReplayError as exc:
        raise ReplayIsolationUnavailable(str(exc)) from exc
