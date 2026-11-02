"""Process-local final-write leases for Hue lighting only.

Leases are freshness evidence, never permission by themselves. Normal leases
observe both newer semantic intent and acknowledged physical writes. Intent-only
leases are setup checkpoints: they ignore acknowledgement churn from the setup
itself, but any newer semantic/lifecycle/owner intent still revokes them.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Iterable
from time import monotonic as _native_monotonic


@dataclass(frozen=True)
class LightingAcceptanceReceipt:
    """One committed outbound command; not a transport acknowledgement."""
    command: object
    lease: LightingLease


class DeskAcceptanceGuard:
    """Raw, callback-free V1 commit, separate from loop policy evaluation.

    Conservatively rejects any source publication since planning, including
    conflicting-source ABA. The original deadline is never renewed.
    """

    def __init__(self, engine, presence, monotonic_deadline, *,
                 conflict_not_after=None, source_readings=None):
        self.engine = engine.__dict__
        self.presence = presence.__dict__
        self.gate = self.presence.get("_physical_source_gate")
        self.source_context = getattr(presence, "physical_source_acceptance_gate", None)
        self.deadline = monotonic_deadline
        self.conflict_not_after = conflict_not_after
        self.snapshot = None
        if self.gate is not None:
            with self.gate:
                # Bind the precomputed time bound to the exact sources used
                # outside the gate. A publication during capture fails closed.
                readings = self.presence.get("_readings", {})
                if source_readings is None or all(
                    readings.get(key) is value for key, value in source_readings
                ):
                    self.snapshot = self._snapshot()

    def _snapshot(self):
        return (
            tuple(sorted((key, id(value)) for key, value in
                         self.presence.get("_readings", {}).items())),
            tuple(sorted(self.presence.get("_physical_source_generations", {}).items())),
            self.engine.get("_desk_owner_generation", 0),
            self.engine.get("_mode_transition_revision", 0),
            tuple((key, id(self.engine.get(key))) for key in (
                "_desk_activity_owner", "_current_mode", "_manual_override",
                "_override_mode", "_mode_source_key", "_enabled", "_away_hold",
                "_host_return_hold", "_external_off_detected")),
        )

    def commit(self, authority, lease, light_id, state, protect):
        # All policy/getters ran on-loop before this short synchronous scope.
        # Native monotonic sampling also accounts for time spent waiting on it.
        if self.gate is None or self.snapshot is None:
            return None
        with self.gate:
            accepted_at = _native_monotonic()
            if (
                accepted_at > self.deadline
                or (self.conflict_not_after is not None
                    and accepted_at >= self.conflict_not_after)
                or self.snapshot != self._snapshot()
                or not authority._valid_raw(lease)
                or (protect and (light_id in state.manual_light_overrides
                                 or light_id in state.transit_light_overrides))
            ):
                return None
            return LightingAcceptanceReceipt(object(), lease)


@dataclass(frozen=True)
class LightingLease:
    instance: object
    producer: str
    global_generation: int
    light_generations: tuple[tuple[str, int], ...]
    whole_generation: int | None = None
    intent_only: bool = False


class LightingAuthority:
    """Monotonic process-local global + per-light Hue authority generations."""

    def __init__(self, boundary) -> None:
        self._source_gate = None
        self._boundary = boundary
        self._instance = object()
        self._global = 0
        self._whole = 0
        self._lights: dict[str, int] = {}
        self._intent_global = 0
        self._intent_whole = 0
        self._intent_lights: dict[str, int] = {}
        self._closed = False

    def bind_source_gate(self, gate) -> None:
        """Bind this authority only; called before engine publication begins.

        The gate is the instance-owned PresenceFusion reentrant context manager.
        No async boundary acquisition or external callbacks belong in its scope.
        Rebinding to another source would split acceptance authority and is refused.
        """
        if not callable(gate):
            return
        if self._source_gate is not None and self._source_gate != gate:
            raise RuntimeError("Lighting authority already bound to another source gate")
        self._source_gate = gate

    def publication_gate(self):
        return self._source_gate() if self._source_gate is not None else nullcontext()

    def invalidate(
        self,
        light_ids: Iterable[str] | None = None,
        *,
        intent: bool = True,
    ) -> None:
        """Publish newer intent or an acknowledged physical mutation.

        Every invalidation advances the ordinary generations. Only semantic
        intent advances the intent-only generations. Targeted invalidations
        keep disjoint per-light leases valid while always revoking whole-scene
        leases through the whole-apartment generation.
        """
        normalized = None if light_ids is None else set(map(str, light_ids))
        intent = bool(intent)
        with self.publication_gate():
            self._invalidate_normalized(normalized, intent=intent)

    def _invalidate_normalized(self, normalized, *, intent):
        """Primitive generation mutation; caller holds publication gate."""
        if normalized is None:
            self._global += 1
            if intent:
                self._intent_global += 1
        else:
            if not normalized:
                return
            for light_id in normalized:
                self._lights[light_id] = self._lights.get(light_id, 0) + 1
                if intent:
                    self._intent_lights[light_id] = (
                        self._intent_lights.get(light_id, 0) + 1
                    )
        self._whole += 1
        if intent:
            self._intent_whole += 1

    def issue(
        self,
        producer: str,
        light_ids: Iterable[str] | None,
        *,
        intent_only: bool = False,
    ) -> LightingLease:
        """Capture current authority. None means whole-apartment scope."""
        ids = None if light_ids is None else sorted(set(map(str, light_ids)))
        producer = str(producer)
        intent_only = bool(intent_only)
        with self.publication_gate():
            if intent_only:
                global_generation = self._intent_global
                light_source = self._intent_lights
                whole_generation = self._intent_whole if ids is None else None
            else:
                global_generation = self._global
                light_source = self._lights
                whole_generation = self._whole if ids is None else None
            return LightingLease(
                instance=self._instance,
                producer=producer,
                global_generation=global_generation,
                light_generations=tuple(
                    (light_id, light_source.get(light_id, 0))
                    for light_id in (ids or ())
                ),
                whole_generation=whole_generation,
                intent_only=intent_only,
            )

    def valid(self, lease: LightingLease | None) -> bool:
        """Validate only while the caller owns the final transition boundary."""
        if not (
            self._boundary.held_by_current_task
            or self._boundary.delegated_worker_validator_active
        ):
            raise RuntimeError(
                "Lighting lease validation requires the final boundary"
            )
        with self.publication_gate():
            return self._valid_raw(lease)

    def _valid_raw(self, lease):
        """Primitive lease check; caller holds publication/source gate."""
        if self._closed or lease is None or lease.instance is not self._instance:
            return False
        if lease.intent_only:
            global_generation = self._intent_global
            light_source = self._intent_lights
            whole_generation = self._intent_whole
        else:
            global_generation = self._global
            light_source = self._lights
            whole_generation = self._whole
        return bool(
            lease.global_generation == global_generation
            and (
                lease.whole_generation is None
                or lease.whole_generation == whole_generation
            )
            and all(
                light_source.get(light_id, 0) == generation
                for light_id, generation in lease.light_generations
            )
        )

    def close(self) -> None:
        with self.publication_gate():
            self._closed = True
            self._invalidate_normalized(None, intent=True)


def engine_publication_gate(instance):
    """Resolve/bind outside the gate, including constructor-bypassing fixtures."""
    state = instance.__dict__
    presence = state.get("_presence_fusion")
    gate = getattr(presence, "physical_source_acceptance_gate", None)
    if not callable(gate):
        return nullcontext()
    boundary = state.get("_transition_boundary")
    if boundary is not None:
        boundary.authority.bind_source_gate(gate)
    return gate()


class LightingSemanticField:
    """Descriptor that publishes engine semantic/lifecycle changes immediately."""

    def __init__(
        self, *, mode_transition: bool = False, underlying_mode: bool = False,
    ) -> None:
        # Mode fan-out needs its own epoch: scene/effect bookkeeping performed
        # by an apply legitimately invalidates Hue leases, but is not a new
        # Activity owner. Do not use those write generations as callback tokens.
        self._mode_transition = mode_transition
        self._underlying_mode = underlying_mode

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return instance.__dict__.get(self._name)

    def __set__(self, instance, value) -> None:
        # Equality can invoke user-defined code. Compare outside the gate, then
        # verify snapshot identity under it before publishing; retry on a race.
        state = instance.__dict__
        while True:
            previous = state.get(self._name)
            changed = bool(previous != value)
            manual_override = state.get("_manual_override")
            overridden = bool(manual_override) if self._underlying_mode else False
            gate = engine_publication_gate(instance)
            with gate:
                if (
                    state.get(self._name) is not previous
                    or (self._underlying_mode and state.get("_manual_override") is not manual_override)
                ):
                    continue
                state[self._name] = value
                if (
                    changed and self._mode_transition
                    and not overridden
                ):
                    state["_mode_transition_revision"] = (
                        state.get("_mode_transition_revision", 0) + 1
                    )
                boundary = state.get("_transition_boundary")
                if boundary is not None and changed:
                    boundary.authority.invalidate()
                return

    @staticmethod
    def advance_owner_revision(instance) -> None:
        """Publish same-mode/explicit owner ABA and revoke leases together."""
        gate = engine_publication_gate(instance)
        with gate:
            state = instance.__dict__
            state["_mode_transition_revision"] = state.get("_mode_transition_revision", 0) + 1
            boundary = state.get("_transition_boundary")
            if boundary is not None:
                boundary.authority.invalidate()
