"""
Shared mutable per-light engine state — GH#87 prerequisite (step 4a of
the automation_engine decomposition).

Groups the three dicts that the upcoming ``light_override_manager``
(step 4) and ``light_applicator`` (step 5) extractions must share with
the engine, so both can hold ONE owner object instead of reaching back
into engine attributes.

Plain dict fields on purpose (critic #4): the 0.5s poll/gather hot path
does direct O(1) membership checks, reads, and writes on these — no
per-light method indirection is allowed here. Policy (when to stamp,
when to wipe, what expires) stays with the engine / future managers;
this class is deliberately behavior-free.

AutomationEngine exposes back-compat property facades under the
original attribute names (``_last_applied_per_light`` etc.), so
existing call sites, tests that rebind the dicts, and the notifier's
``getattr`` reach-through all keep working unchanged.
"""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class EngineState:
    """Per-light shared state: dedup cache + manual/transit override stamps."""

    # Last state dict written to the bridge per light — the dedup cache.
    # Reconcile skips a write when the computed state equals this entry.
    # Invalidated (rebound to {}) via the engine's _invalidate_dedup_cache.
    last_applied_per_light: dict[str, dict] = field(default_factory=dict)

    # light_id → stamp time. Lights here are protected from automation
    # until the next user-initiated mode change (see
    # PRESERVE_PER_LIGHT_OVERRIDE_SOURCES) or 4h expiry in run_loop.
    manual_light_overrides: dict[str, datetime] = field(default_factory=dict)

    # light_id → expiration deadline. Owned jointly by
    # TransitLightingService + DeskExitKitchenService through the engine
    # verbs; reconcile skips these lights like manual overrides.
    transit_light_overrides: dict[str, datetime] = field(default_factory=dict)
