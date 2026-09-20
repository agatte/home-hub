"""Central evidence-backed Sonos ownership leases (#274)."""
from __future__ import annotations

import asyncio
import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

logger = logging.getLogger("home_hub.audio_ownership")

AUDIO_OWNERSHIP_SETTING_KEY = "audio_ownership_leases"
AUDIO_OWNERSHIP_VERSION = 1

QUEUE_SOURCE = "queue_source"
TRANSPORT = "transport"
VOLUME = "volume"
INTERRUPTION = "interruption"
AUDIO_DIMENSIONS = frozenset({QUEUE_SOURCE, TRANSPORT, VOLUME, INTERRUPTION})

MANUAL_TRANSPORT_DIMENSIONS = frozenset({QUEUE_SOURCE, TRANSPORT, INTERRUPTION})
MANUAL_QUEUE_DIMENSIONS = MANUAL_TRANSPORT_DIMENSIONS
MANUAL_VOLUME_DIMENSIONS = frozenset({VOLUME, INTERRUPTION})

LEASE_TYPE_EXCLUSIVE = "exclusive"
LEASE_TYPE_INTERRUPTION = "interruption"

SettingLoader = Callable[[str], Awaitable[dict]]
SettingSaver = Callable[[str, dict], Awaitable[None]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dimensions(values: Iterable[str]) -> frozenset[str]:
    dims = frozenset(str(value) for value in values)
    unknown = dims - AUDIO_DIMENSIONS
    if not dims or unknown:
        raise ValueError(f"invalid audio ownership dimensions: {sorted(unknown or dims)}")
    return dims


class AudioOwnershipService:
    """Durable lease registry for autonomous Sonos writers.

    Leases grant no device authority by themselves. Callers must still prove
    live Sonos evidence before every consequential write/release. The registry
    answers only the shared question: which HomeHub subsystem still owns which
    dimensions, and has a newer/manual intent invalidated that claim?
    """

    def __init__(self, *, setting_loader: SettingLoader, setting_saver: SettingSaver) -> None:
        self._load_setting = setting_loader
        self._save_setting = setting_saver
        self._lock = asyncio.Lock()
        self._loaded = False
        self._generation = 0
        self._leases: dict[str, dict[str, Any]] = {}
        self._last_invalidation: dict[str, Any] | None = None
        # Ephemeral per-dimension epochs for low-priority/opportunistic writers.
        # These deliberately do not persist: no opportunistic operation survives
        # process restart, while durable leases still do.
        self._opportunistic_epochs: dict[str, int] = {
            dimension: 0 for dimension in AUDIO_DIMENSIONS
        }

    def _touch_opportunistic_locked(self, dimensions: Iterable[str]) -> None:
        for dimension in dimensions:
            self._opportunistic_epochs[dimension] += 1


    async def load(self) -> None:
        async with self._lock:
            await self._load_locked()

    async def _load_locked(self) -> None:
        if self._loaded:
            return
        raw = await self._load_setting(AUDIO_OWNERSHIP_SETTING_KEY) or {}
        if raw.get("version") == AUDIO_OWNERSHIP_VERSION:
            try:
                self._generation = max(0, int(raw.get("generation") or 0))
            except (TypeError, ValueError):
                self._generation = 0
            leases = raw.get("leases")
            if isinstance(leases, dict):
                for lease_id, lease in leases.items():
                    if not isinstance(lease, dict):
                        continue
                    dims = frozenset(lease.get("dimensions") or ())
                    if not dims or not dims <= AUDIO_DIMENSIONS:
                        continue
                    item = deepcopy(lease)
                    item["lease_id"] = str(lease_id)
                    item["dimensions"] = sorted(dims)
                    item["lease_type"] = (
                        LEASE_TYPE_INTERRUPTION
                        if item.get("lease_type") == LEASE_TYPE_INTERRUPTION
                        else LEASE_TYPE_EXCLUSIVE
                    )
                    self._leases[str(lease_id)] = item
            last = raw.get("last_invalidation")
            if isinstance(last, dict):
                self._last_invalidation = deepcopy(last)
        elif raw:
            logger.warning("Ignoring malformed/unsupported persisted audio ownership state")
        self._loaded = True

    async def _persist_locked(self) -> None:
        await self._save_setting(
            AUDIO_OWNERSHIP_SETTING_KEY,
            {
                "version": AUDIO_OWNERSHIP_VERSION,
                "generation": self._generation,
                "leases": deepcopy(self._leases),
                "last_invalidation": deepcopy(self._last_invalidation),
            },
        )


    async def acquire(
        self,
        *,
        owner: str,
        purpose: str,
        dimensions: Iterable[str],
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        requested = _dimensions(dimensions)
        owner = str(owner).strip()
        purpose = str(purpose).strip()
        if not owner or not purpose:
            raise ValueError("owner and purpose are required")

        async with self._lock:
            await self._load_locked()
            for lease in self._leases.values():
                if requested.intersection(lease.get("dimensions") or ()):
                    return None
            self._generation += 1
            self._touch_opportunistic_locked(requested)
            lease_id = uuid.uuid4().hex
            lease = {
                "lease_id": lease_id,
                "owner": owner,
                "purpose": purpose,
                "lease_type": LEASE_TYPE_EXCLUSIVE,
                "dimensions": sorted(requested),
                "generation": self._generation,
                "evidence": deepcopy(evidence or {}),
                "metadata": deepcopy(metadata or {}),
                "created_at": _utc_now_iso(),
            }
            self._leases[lease_id] = lease
            await self._persist_locked()
            logger.info(
                "audio ownership acquired owner=%s purpose=%s dims=%s gen=%s",
                owner, purpose, ",".join(sorted(requested)), self._generation,
            )
            return deepcopy(lease)

    async def acquire_interruption(
        self,
        *,
        owner: str,
        purpose: str,
        dimensions: Iterable[str],
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        manual_source: str | None = None,
        manual_reason: str | None = None,
    ) -> dict[str, Any] | None:
        """Acquire a temporary overlay lease for a serialized interruption.

        Interruption leases may overlap ordinary autonomous leases. Existing
        owners keep their provenance, but run_if_valid blocks their writes for
        overlapping dimensions until the interruption retires. A second
        overlapping interruption is refused. Autonomous interruptions also
        refuse a conflicting reserved transaction; explicit manual
        interruptions atomically retire that unfinished reservation first.
        """
        requested = _dimensions(dimensions)
        if INTERRUPTION not in requested:
            raise ValueError("interruption lease must include interruption dimension")
        owner = str(owner).strip()
        purpose = str(purpose).strip()
        if not owner or not purpose:
            raise ValueError("owner and purpose are required")

        async with self._lock:
            await self._load_locked()

            # Never displace an in-flight interruption. Check this before
            # retiring any reserved autonomous work so a second TTS request
            # cannot cause side effects merely by failing acquisition.
            for lease in self._leases.values():
                held = frozenset(lease.get("dimensions") or ())
                if (
                    lease.get("lease_type") == LEASE_TYPE_INTERRUPTION
                    and requested.intersection(held)
                ):
                    return None

            preempted: list[dict[str, Any]] = []
            for lease_id, lease in list(self._leases.items()):
                held = frozenset(lease.get("dimensions") or ())
                overlap = requested.intersection(held)
                if not overlap:
                    continue
                phase = str((lease.get("evidence") or {}).get("phase") or "")
                if phase != "reserved":
                    continue
                if manual_source is None:
                    return None
                preempted.append({
                    "lease_id": lease_id,
                    "owner": lease.get("owner"),
                    "purpose": lease.get("purpose"),
                    "dimensions": sorted(overlap),
                })
                # A reservation is one unfinished transaction; partial
                # dimensional survival would leave an unusable zombie claim.
                del self._leases[lease_id]

            if preempted:
                self._generation += 1
                self._last_invalidation = {
                    "generation": self._generation,
                    "source": str(manual_source or "manual")[:80],
                    "reason": str(
                        manual_reason or "manual_interruption_preempt_reserved"
                    )[:120],
                    "dimensions": sorted(requested),
                    "invalidated": deepcopy(preempted),
                    "created_at": _utc_now_iso(),
                }
                logger.info(
                    "manual interruption preempted reserved audio work "
                    "source=%s reason=%s leases=%s gen=%s",
                    manual_source,
                    manual_reason or "manual_interruption_preempt_reserved",
                    ",".join(item["lease_id"] for item in preempted),
                    self._generation,
                )

            # Remaining overlapping exclusive owners are established sessions
            # and intentionally survive underneath the interruption overlay.
            # Persist the exact identities so a restart/shutdown abandonment can
            # retire stale underlying authority without touching Sonos.
            overlaid_lease_ids = sorted(
                lease_id
                for lease_id, lease in self._leases.items()
                if lease.get("lease_type") != LEASE_TYPE_INTERRUPTION
                and requested.intersection(lease.get("dimensions") or ())
            )

            self._generation += 1
            self._touch_opportunistic_locked(requested)
            lease_id = uuid.uuid4().hex
            lease = {
                "lease_id": lease_id,
                "owner": owner,
                "purpose": purpose,
                "lease_type": LEASE_TYPE_INTERRUPTION,
                "dimensions": sorted(requested),
                "generation": self._generation,
                "evidence": deepcopy(evidence or {}),
                "metadata": deepcopy(metadata or {}),
                "overlaid_lease_ids": overlaid_lease_ids,
                "created_at": _utc_now_iso(),
            }
            self._leases[lease_id] = lease
            await self._persist_locked()
            logger.info(
                "audio interruption acquired owner=%s purpose=%s dims=%s gen=%s",
                owner, purpose, ",".join(sorted(requested)), self._generation,
            )
            return deepcopy(lease)

    async def update_evidence(
        self, lease_id: str, evidence: dict[str, Any],
    ) -> bool:
        async with self._lock:
            await self._load_locked()
            lease = self._leases.get(str(lease_id))
            if lease is None:
                return False
            lease["evidence"] = deepcopy(evidence)
            lease["evidence_updated_at"] = _utc_now_iso()
            await self._persist_locked()
            return True

    async def find_lease(
        self, *, owner: str, purpose: str | None = None,
    ) -> dict[str, Any] | None:
        async with self._lock:
            await self._load_locked()
            matches = [
                lease for lease in self._leases.values()
                if lease.get("owner") == owner
                and (purpose is None or lease.get("purpose") == purpose)
            ]
            if not matches:
                return None
            lease = max(matches, key=lambda item: int(item.get("generation") or 0))
            return deepcopy(lease)

    async def is_valid(
        self, lease_id: str, dimensions: Iterable[str] | None = None,
    ) -> bool:
        async with self._lock:
            await self._load_locked()
            lease = self._leases.get(str(lease_id))
            if lease is None:
                return False
            if dimensions is None:
                return True
            requested = _dimensions(dimensions)
            return requested <= frozenset(lease.get("dimensions") or ())

    async def is_interrupted(
        self,
        lease_id: str,
        dimensions: Iterable[str],
    ) -> bool:
        """Whether a newer temporary interruption overlays this lease."""
        requested = _dimensions(dimensions)
        async with self._lock:
            await self._load_locked()
            current = self._leases.get(str(lease_id))
            if current is None:
                return False
            for other_id, lease in self._leases.items():
                if other_id == str(lease_id):
                    continue
                if lease.get("lease_type") != LEASE_TYPE_INTERRUPTION:
                    continue
                if requested.intersection(lease.get("dimensions") or ()):
                    return True
            return False

    async def invalidate_opportunistic(
        self, dimensions: Iterable[str],
    ) -> dict[str, int]:
        """Invalidate low-priority writers without disturbing durable leases."""
        requested = _dimensions(dimensions)
        async with self._lock:
            await self._load_locked()
            self._touch_opportunistic_locked(requested)
            return {
                dimension: self._opportunistic_epochs[dimension]
                for dimension in sorted(requested)
            }

    async def capture_opportunistic(
        self, dimensions: Iterable[str],
    ) -> dict[str, int] | None:
        """Capture an epoch token only while the requested dimensions are free."""
        requested = _dimensions(dimensions)
        async with self._lock:
            await self._load_locked()
            for lease in self._leases.values():
                if requested.intersection(lease.get("dimensions") or ()):
                    return None
            return {
                dimension: self._opportunistic_epochs[dimension]
                for dimension in sorted(requested)
            }

    async def run_if_opportunistic(
        self,
        token: dict[str, int],
        operation: Callable[[], Awaitable[Any]],
    ) -> tuple[bool, Any]:
        """Run a low-priority write only if its dimensions remain free/current.

        The check and write share the same authority lock as manual actions and
        durable lease acquisition. A stronger owner or a newer invalidation can
        therefore finish the current step but prevents every later stale step.
        """
        requested = _dimensions(token.keys())
        expected = {dimension: int(token[dimension]) for dimension in requested}
        async with self._lock:
            await self._load_locked()
            for lease in self._leases.values():
                if requested.intersection(lease.get("dimensions") or ()):
                    return False, None
            if any(
                self._opportunistic_epochs[dimension] != expected[dimension]
                for dimension in requested
            ):
                return False, None
            return True, await operation()

    async def run_if_valid(
        self,
        lease_id: str,
        dimensions: Iterable[str],
        operation: Callable[[], Awaitable[Any]],
    ) -> tuple[bool, Any]:
        """Serialize one autonomous write against manual invalidation.

        A temporary interruption lease overlays ordinary owners without
        destroying their provenance. While the overlay is active, writes from
        an overlapped ordinary lease are refused; the interruption owner itself
        remains eligible for the dimensions it still holds.
        """
        requested = _dimensions(dimensions)
        async with self._lock:
            await self._load_locked()
            lease = self._leases.get(str(lease_id))
            if lease is None:
                return False, None
            if not requested <= frozenset(lease.get("dimensions") or ()):
                return False, None
            if lease.get("lease_type") != LEASE_TYPE_INTERRUPTION:
                for other_id, other in self._leases.items():
                    if other_id == str(lease_id):
                        continue
                    if other.get("lease_type") != LEASE_TYPE_INTERRUPTION:
                        continue
                    if requested.intersection(other.get("dimensions") or ()):
                        return False, None
            return True, await operation()

    async def release(
        self,
        lease_id: str,
        *,
        dimensions: Iterable[str] | None = None,
        reason: str = "released",
    ) -> bool:
        async with self._lock:
            await self._load_locked()
            lease = self._leases.get(str(lease_id))
            if lease is None:
                return False
            held = frozenset(lease.get("dimensions") or ())
            selected = held if dimensions is None else _dimensions(dimensions)
            selected &= held
            if not selected:
                return False
            remaining = held - selected
            self._generation += 1
            self._touch_opportunistic_locked(selected)
            if remaining:
                lease["dimensions"] = sorted(remaining)
                lease["generation"] = self._generation
            else:
                del self._leases[str(lease_id)]
            await self._persist_locked()
            logger.info(
                "audio ownership released lease=%s dims=%s reason=%s gen=%s",
                lease_id, ",".join(sorted(selected)), reason, self._generation,
            )
            return True

    async def abandon_interruption(
        self,
        lease_id: str,
        *,
        reason: str = "interruption_abandoned",
    ) -> list[dict[str, Any]]:
        """Retire an interruption and the established owners it overlaid.

        Use this only when the interruption cannot prove a safe restore
        (restart/shutdown/fatal restore failure). No device mutation occurs.
        """
        async with self._lock:
            await self._load_locked()
            interruption = self._leases.get(str(lease_id))
            if (
                interruption is None
                or interruption.get("lease_type") != LEASE_TYPE_INTERRUPTION
            ):
                return []

            retired: list[dict[str, Any]] = []
            for overlaid_id in interruption.get("overlaid_lease_ids") or ():
                overlaid_id = str(overlaid_id)
                lease = self._leases.get(overlaid_id)
                if (
                    lease is None
                    or lease.get("lease_type") == LEASE_TYPE_INTERRUPTION
                ):
                    continue
                retired.append({
                    "lease_id": overlaid_id,
                    "owner": lease.get("owner"),
                    "purpose": lease.get("purpose"),
                    "dimensions": list(lease.get("dimensions") or ()),
                })
                del self._leases[overlaid_id]

            touched_dimensions = set(interruption.get("dimensions") or ())
            for item in retired:
                touched_dimensions.update(item.get("dimensions") or ())
            del self._leases[str(lease_id)]
            self._generation += 1
            self._touch_opportunistic_locked(touched_dimensions)
            await self._persist_locked()
            logger.info(
                "audio interruption abandoned lease=%s overlaid=%s reason=%s gen=%s",
                lease_id,
                ",".join(item["lease_id"] for item in retired) or "none",
                reason,
                self._generation,
            )
            return deepcopy(retired)

    async def _invalidate_manual_locked(
        self,
        selected: frozenset[str],
        *,
        source: str,
        reason: str,
    ) -> dict[str, Any]:
        invalidated: list[dict[str, Any]] = []
        for lease_id, lease in list(self._leases.items()):
            held = frozenset(lease.get("dimensions") or ())
            overlap = held & selected
            if not overlap:
                continue
            invalidated.append({
                "lease_id": lease_id,
                "owner": lease.get("owner"),
                "purpose": lease.get("purpose"),
                "dimensions": sorted(overlap),
            })
            remaining = held - overlap
            if remaining:
                lease["dimensions"] = sorted(remaining)
            else:
                del self._leases[lease_id]

        self._generation += 1
        self._touch_opportunistic_locked(selected)
        self._last_invalidation = {
            "generation": self._generation,
            "source": str(source or "manual")[:80],
            "reason": str(reason or "manual_action")[:120],
            "dimensions": sorted(selected),
            "invalidated": deepcopy(invalidated),
            "created_at": _utc_now_iso(),
        }
        await self._persist_locked()
        if invalidated:
            logger.info(
                "manual audio invalidation source=%s reason=%s dims=%s leases=%s gen=%s",
                source, reason, ",".join(sorted(selected)),
                ",".join(item["lease_id"] for item in invalidated),
                self._generation,
            )
        return deepcopy(self._last_invalidation)

    async def invalidate_manual(
        self,
        dimensions: Iterable[str],
        *,
        source: str,
        reason: str,
    ) -> dict[str, Any]:
        selected = _dimensions(dimensions)
        async with self._lock:
            await self._load_locked()
            return await self._invalidate_manual_locked(
                selected, source=source, reason=reason,
            )

    async def run_manual(
        self,
        dimensions: Iterable[str],
        *,
        source: str,
        reason: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Invalidate conflicting leases and serialize the manual write."""
        selected = _dimensions(dimensions)
        async with self._lock:
            await self._load_locked()
            await self._invalidate_manual_locked(
                selected, source=source, reason=reason,
            )
            return await operation()

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            await self._load_locked()
            return {
                "version": AUDIO_OWNERSHIP_VERSION,
                "generation": self._generation,
                "leases": sorted(
                    (deepcopy(lease) for lease in self._leases.values()),
                    key=lambda item: int(item.get("generation") or 0),
                ),
                "last_invalidation": deepcopy(self._last_invalidation),
            }
