"""Passive policy helpers for the replay-reached Activity boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from backend.services.automation_constants import (
    AUTONOMOUS_PUSH_SOURCES,
    SOURCE_STALE_SECONDS,
)


class DesktopInteractionEvidence(Protocol):
    """Minimum process evidence consumed by navigation attendance."""

    received_at: datetime
    idle_seconds: float | None


def project_current_mode(
    manual_override: bool,
    override_mode: str | None,
    current_mode: str,
) -> str:
    if manual_override:
        return override_mode or current_mode
    return current_mode


def project_house_state(away_hold: bool, current_mode: str | None) -> str:
    if away_hold:
        return "away"
    if current_mode is None:
        raise ValueError("current_mode is required while not away")
    if current_mode == "sleeping":
        return "sleeping"
    return "home"


def project_activity(
    house_state: str,
    current_mode: str | None,
) -> str | None:
    if house_state != "home":
        return None
    if current_mode is None:
        raise ValueError("current_mode is required while home")
    if current_mode in {"idle", "away"}:
        return "general"
    if current_mode == "sleeping":
        return None
    return current_mode


def project_effective_mode(
    house_state: str,
    activity: str | None,
    current_mode: str | None,
) -> str:
    if house_state == "away":
        return "away"
    if house_state == "sleeping":
        return "sleeping"
    if activity is not None:
        return activity
    if current_mode is None:
        raise ValueError("current_mode is required without activity")
    return current_mode


def has_fresh_mode_replacement(
    current_mode: str,
    mode_source: str,
    mode_source_key: str,
    report_times: dict[str, datetime],
    now: datetime,
) -> bool:
    if current_mode == "idle":
        return False
    last_report = report_times.get(
        mode_source_key,
        report_times.get(mode_source),
    )
    return bool(
        last_report
        and (now - last_report).total_seconds() < SOURCE_STALE_SECONDS
    )


def override_is_user_owned(
    manual_override: bool,
    override_source: str | None,
) -> bool:
    return bool(
        manual_override
        and override_source not in AUTONOMOUS_PUSH_SOURCES
    )


def is_recent_desktop_interaction(
    evidence: DesktopInteractionEvidence | None,
    now: datetime,
    *,
    max_idle_seconds: float,
    max_report_age_seconds: float,
) -> bool:
    if evidence is None or evidence.idle_seconds is None:
        return False
    age = (now - evidence.received_at).total_seconds()
    return bool(
        -2.0 <= age <= max_report_age_seconds
        and 0.0 <= evidence.idle_seconds < max_idle_seconds
    )


OverrideExpiryAction = Literal[
    "none",
    "release_autonomous",
    "release_fresh_replacement",
    "defer",
]


@dataclass(frozen=True)
class OverrideExpiryDecision:
    suspend_idle_dwell: bool = False
    action: OverrideExpiryAction = "none"


def evaluate_override_expiry(
    *,
    manual_override: bool,
    override_time: datetime | None,
    override_mode: str | None,
    override_source: str | None,
    override_timeout_hours: float,
    current_mode: str,
    mode_source: str,
    mode_source_key: str,
    report_times: dict[str, datetime],
    now: datetime,
    expiry_deferred: bool,
) -> OverrideExpiryDecision:
    eligible = bool(
        manual_override
        and override_time is not None
        and override_mode != "sleeping"
        and override_source != "physical_context_relax"
    )
    if not eligible:
        return OverrideExpiryDecision()

    elapsed = now - override_time
    if elapsed <= timedelta(hours=override_timeout_hours):
        return OverrideExpiryDecision(suspend_idle_dwell=True)

    if not override_is_user_owned(manual_override, override_source):
        return OverrideExpiryDecision(
            suspend_idle_dwell=True,
            action="release_autonomous",
        )

    if has_fresh_mode_replacement(
        current_mode,
        mode_source,
        mode_source_key,
        report_times,
        now,
    ):
        return OverrideExpiryDecision(
            suspend_idle_dwell=True,
            action="release_fresh_replacement",
        )

    if not expiry_deferred:
        return OverrideExpiryDecision(
            suspend_idle_dwell=True,
            action="defer",
        )
    return OverrideExpiryDecision(suspend_idle_dwell=True)
