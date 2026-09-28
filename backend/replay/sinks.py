"""Closed, in-memory side-effect sinks for navigation-v1 replay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ReplaySinkError(RuntimeError):
    """A replay side effect cannot be resolved by the closed sink policy."""


@dataclass(frozen=True)
class RecordingLightRequest:
    sequence: int
    light_id: str
    payload: dict[str, Any]
    policy_source: str
    result: bool | None
    error: str | None = None


def _parse_outcome(value: Any, label: str) -> bool | ReplaySinkError:
    if type(value) is bool:
        return value
    if (
        isinstance(value, dict)
        and set(value) == {"status", "message"}
        and value["status"] == "error"
        and isinstance(value["message"], str)
        and value["message"]
    ):
        return ReplaySinkError(f"{label}: {value['message']}")
    raise ReplaySinkError(f"{label}: adapter outcome must be bool or explicit error")


class RecordingLightSink:
    """Hue-shaped adapter whose entire behavior comes from closed replay data."""

    def __init__(
        self,
        *,
        connected: bool,
        available: bool,
        result_policy: dict[str, Any],
    ) -> None:
        if type(connected) is not bool or type(available) is not bool:
            raise ReplaySinkError("adapter availability must be boolean")
        if not isinstance(result_policy, dict):
            raise ReplaySinkError("adapter result_policy must be an object")
        extra = set(result_policy) - {"default", "by_light", "by_request"}
        if extra:
            raise ReplaySinkError(f"adapter result_policy has unsupported keys: {sorted(extra)}")

        self.connected = connected and available
        self.available = available
        self.requests: list[RecordingLightRequest] = []
        self.settle_attempts: list[tuple[str, ...]] = []
        self._default = (
            _parse_outcome(result_policy["default"], "result_policy.default")
            if "default" in result_policy
            else None
        )
        self._by_light = self._parse_mapping(
            result_policy.get("by_light", {}),
            "result_policy.by_light",
        )
        self._by_request = self._parse_mapping(
            result_policy.get("by_request", {}),
            "result_policy.by_request",
            request_keys=True,
        )

    @staticmethod
    def _parse_mapping(
        value: Any,
        label: str,
        *,
        request_keys: bool = False,
    ) -> dict[str, bool | ReplaySinkError]:
        if not isinstance(value, dict):
            raise ReplaySinkError(f"{label} must be an object")
        parsed: dict[str, bool | ReplaySinkError] = {}
        for raw_key, outcome in value.items():
            key = str(raw_key)
            if request_keys and (not key.isdigit() or int(key) < 1):
                raise ReplaySinkError(f"{label} request keys must be positive integers")
            if not request_keys and not key:
                raise ReplaySinkError(f"{label} light ids must be nonempty")
            parsed[key] = _parse_outcome(outcome, f"{label}.{key}")
        return parsed

    def _resolve(self, sequence: int, light_id: str):
        request_key = str(sequence)
        if request_key in self._by_request:
            return self._by_request[request_key], f"by_request:{request_key}"
        if light_id in self._by_light:
            return self._by_light[light_id], f"by_light:{light_id}"
        if self._default is not None:
            return self._default, "default"
        return None, "unmatched"

    async def set_light(self, light_id: str, payload: dict[str, Any]) -> bool:
        sequence = len(self.requests) + 1
        light_id = str(light_id)
        detached = dict(payload)
        outcome, source = self._resolve(sequence, light_id)
        if outcome is None:
            self.requests.append(
                RecordingLightRequest(
                    sequence=sequence,
                    light_id=light_id,
                    payload=detached,
                    policy_source=source,
                    result=None,
                    error="no deterministic adapter outcome",
                )
            )
            raise ReplaySinkError(
                f"request {sequence} light {light_id} has no deterministic adapter outcome"
            )
        if isinstance(outcome, ReplaySinkError):
            self.requests.append(
                RecordingLightRequest(
                    sequence=sequence,
                    light_id=light_id,
                    payload=detached,
                    policy_source=source,
                    result=None,
                    error=str(outcome),
                )
            )
            raise outcome

        self.requests.append(
            RecordingLightRequest(
                sequence=sequence,
                light_id=light_id,
                payload=detached,
                policy_source=source,
                result=outcome,
            )
        )
        return outcome

    async def wait_for_transition_settle(self, light_ids) -> None:
        """Fail closed if a replay-excluded physical-settle path becomes reachable."""

        ids = tuple(str(light_id) for light_id in light_ids)
        self.settle_attempts.append(ids)
        raise ReplaySinkError("physical transition settling is outside navigation-v1 replay")


class RecordingEventSink:
    """In-memory replacement for SQLite-backed adjustment and ML loggers."""

    def __init__(self) -> None:
        self.light_adjustments: list[dict[str, Any]] = []
        self.learner_decisions: list[dict[str, Any]] = []

    async def log_light_adjustment(self, **fields: Any) -> None:
        self.light_adjustments.append(dict(fields))

    def record_learner_deltas(
        self,
        *,
        period: str,
        deltas: dict[str, dict[str, dict[str, Any]]],
    ) -> None:
        if deltas:
            self.learner_decisions.append(
                {
                    "predicted_mode": "working",
                    "decision_source": "lighting_learner",
                    "period": period,
                    "deltas": deltas,
                }
            )
