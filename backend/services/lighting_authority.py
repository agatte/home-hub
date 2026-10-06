"""Process-local final-write leases for Hue lighting only.

Leases are freshness evidence, never permission by themselves. Normal leases
observe both newer semantic intent and acknowledged physical writes. Intent-only
leases are setup checkpoints: they ignore acknowledgement churn from the setup
itself, but any newer semantic/lifecycle/owner intent still revokes them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


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
        self._boundary = boundary
        self._instance = object()
        self._global = 0
        self._whole = 0
        self._lights: dict[str, int] = {}
        self._intent_global = 0
        self._intent_whole = 0
        self._intent_lights: dict[str, int] = {}
        self._closed = False

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
        if light_ids is None:
            self._global += 1
            if intent:
                self._intent_global += 1
        else:
            normalized = set(map(str, light_ids))
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
            producer=str(producer),
            global_generation=global_generation,
            light_generations=tuple(
                (light_id, light_source.get(light_id, 0))
                for light_id in (ids or ())
            ),
            whole_generation=whole_generation,
            intent_only=bool(intent_only),
        )

    def valid(self, lease: LightingLease | None) -> bool:
        """Validate only while the caller owns the final transition boundary."""
        if not self._boundary.held_by_current_task:
            raise RuntimeError(
                "Lighting lease validation requires the final boundary"
            )
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
        self._closed = True
        self.invalidate()


class LightingSemanticField:
    """Descriptor that publishes engine semantic/lifecycle changes immediately."""

    def __set_name__(self, owner, name) -> None:
        self._name = name

    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        return instance.__dict__.get(self._name)

    def __set__(self, instance, value) -> None:
        previous = instance.__dict__.get(self._name)
        instance.__dict__[self._name] = value
        boundary = instance.__dict__.get("_transition_boundary")
        if boundary is not None and previous != value:
            boundary.authority.invalidate()
