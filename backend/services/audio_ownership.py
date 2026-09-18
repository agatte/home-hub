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
            lease_id = uuid.uuid4().hex
            lease = {
                "lease_id": lease_id,
                "owner": owner,
                "purpose": purpose,
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

    async def run_if_valid(
        self,
        lease_id: str,
        dimensions: Iterable[str],
        operation: Callable[[], Awaitable[Any]],
    ) -> tuple[bool, Any]:
        """Serialize one autonomous write against manual invalidation."""
        requested = _dimensions(dimensions)
        async with self._lock:
            await self._load_locked()
            lease = self._leases.get(str(lease_id))
            if lease is None:
                return False, None
            if not requested <= frozenset(lease.get("dimensions") or ()):
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
