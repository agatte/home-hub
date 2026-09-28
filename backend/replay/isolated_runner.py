"""Fail-closed operational isolation contract for navigation replay.

The in-process replay root is testable evidence, not the operational sandbox.
A supported runner must enforce these restrictions outside the child process.
"""

from __future__ import annotations

from dataclasses import dataclass


class ReplayIsolationUnavailable(RuntimeError):
    """No reviewed OS/container isolation backend is available."""


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


def supported_isolation_backend() -> str | None:
    """Return a reviewed backend name once HomeHub actually has one.

    The repository currently contains no launcher that can establish every
    navigation-v1 isolation guarantee. Returning None is deliberate: a normal
    Python process, including one guarded by monkeypatches, is not the accepted
    no-actuation boundary.
    """

    return None


def require_supported_isolation() -> str:
    backend = supported_isolation_backend()
    if backend is None:
        raise ReplayIsolationUnavailable(
            "navigation-v1 operational replay is disabled: no reviewed "
            "OS/container isolation backend can enforce the required "
            "network/device/subprocess/filesystem restrictions"
        )
    return backend


def run_navigation_v1_isolated(*, bundle_path: str) -> None:
    """Fail closed until an external launcher can enforce REQUIRED_ISOLATION.

    bundle_path is intentionally not opened here. When an isolation backend
    is accepted, the launcher -- not this unrestricted parent process -- must
    expose immutable input and a preopened result stream to the child artifact.
    """

    if not isinstance(bundle_path, str) or not bundle_path:
        raise ValueError("bundle_path must be a nonempty string")
    require_supported_isolation()
    raise AssertionError("unreachable without an accepted isolation backend")
