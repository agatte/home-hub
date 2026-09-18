"""Narrow explicit assisted-playback authority for Music Intelligence (#272).

Music Intelligence may select an exact candidate, but this service is the policy
boundary that decides whether one explicit request may reach MusicMapper/Sonos.
The first slice is deliberately restrictive: exact Apple Music tracks only,
current Sonos transport idle, NORMAL play mode, no ambient/TTS owner, Home/Awake,
DND off, and a current per-mode music-volume curve. It never raises volume.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import unquote

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.database import async_session
from backend.models import MusicAssistedPlaybackEvent, SonosPlaybackEvent
from backend.services.mode_volume_policy import compute_mode_volume
from backend.services.mode_volume_service import MODE_VOLUME_CURVES_KEY
from backend.services.music_trust import MusicApprovalService, MusicTrustPolicy
from backend.services.playlist_catalog import MusicCatalog, VerifiedMusicCandidate

_SUPPORTED_ADAPTER = "sonos_apple_music_share_link"
_IDLE_STATES = frozenset({"STOPPED", "NO_MEDIA_PRESENT"})
_TRAVEL_MARKER = Path.home() / ".local" / "state" / "home-hub" / "travel-mode"
_RETURNING_MARKER = Path.home() / ".local" / "state" / "home-hub" / "returning-home"


def _default_lifecycle_state() -> dict[str, bool]:
    return {
        "travel": _TRAVEL_MARKER.exists(),
        "returning_home": _RETURNING_MARKER.exists(),
    }


class MusicAssistedPlaybackService:
    """Fail-closed explicit playback policy with durable request idempotency."""

    def __init__(
        self,
        *,
        app_state: Any,
        catalog: MusicCatalog,
        taste_provider: Any,
        approval_service: MusicApprovalService,
        trust_policy: MusicTrustPolicy,
        setting_loader: Callable[[str], Awaitable[dict | None]],
        session_factory=async_session,
        lifecycle_state: Callable[[], dict[str, bool]] | None = None,
    ) -> None:
        self._app_state = app_state
        self._catalog = catalog
        self._taste_provider = taste_provider
        self._approval_service = approval_service
        self._trust_policy = trust_policy
        self._setting_loader = setting_loader
        self._session_factory = session_factory
        self._lifecycle_state = lifecycle_state or _default_lifecycle_state
        # One speaker, one explicit assisted transaction at a time. The durable
        # unique client_event_id handles retries across process restarts.
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "explicit_only": True,
            "actuation_allowed": True,
            "autonomous_context_playback": False,
            "supported_adapters": [_SUPPORTED_ADAPTER],
            "ownership_policy": "idle_sonos_only",
            "idempotency": "durable_client_event_id",
            "volume_policy": "require_at_or_below_current_mode_cap_never_write",
        }

    async def play_exact(
        self,
        *,
        client_event_id: str,
        provider: str,
        provider_id: str,
        source: str,
    ) -> dict[str, Any]:
        client_event_id = str(client_event_id or "").strip()
        provider = str(provider or "").strip()
        provider_id = str(provider_id or "").strip()
        source = (str(source or "").strip() or "dashboard:music_assisted")[:80]
        if not client_event_id or len(client_event_id) > 80:
            raise ValueError("client_event_id is required and must be <= 80 characters")
        if not provider or not provider_id:
            raise ValueError("provider and provider_id are required")

        async with self._lock:
            existing = await self._load(client_event_id)
            if existing is not None:
                self._validate_retry_identity(existing, provider, provider_id)
                if existing.status == "pending":
                    existing = await self._complete(
                        client_event_id, status="indeterminate",
                        reason="interrupted_after_claim_no_replay",
                    )
                return self._row_result(existing, duplicate=True)

            candidate = await self._catalog.get_by_identity(provider, provider_id)
            if candidate is None:
                return await self._record_terminal(
                    client_event_id=client_event_id,
                    provider=provider,
                    provider_id=provider_id,
                    source=source,
                    status="suppressed",
                    reason="candidate_unavailable",
                )
            if not candidate.playback_capable:
                return await self._record_terminal(
                    client_event_id=client_event_id,
                    provider=provider,
                    provider_id=provider_id,
                    source=source,
                    candidate=candidate,
                    status="suppressed",
                    reason="candidate_not_playback_capable",
                )
            if candidate.playback_adapter != _SUPPORTED_ADAPTER:
                return await self._record_terminal(
                    client_event_id=client_event_id,
                    provider=provider,
                    provider_id=provider_id,
                    source=source,
                    candidate=candidate,
                    status="suppressed",
                    reason="unsupported_playback_adapter",
                )

            automation = getattr(self._app_state, "automation", None)
            mode = str(getattr(automation, "current_mode", "") or "").strip().casefold()
            trust, trust_error = await self._resolve_trust(candidate, mode=mode or None)
            if trust_error is not None:
                return await self._record_terminal(
                    client_event_id=client_event_id,
                    provider=provider,
                    provider_id=provider_id,
                    source=source,
                    candidate=candidate,
                    status="suppressed",
                    reason=trust_error,
                    mode=mode or None,
                )
            if not trust.playback_eligible or trust.state not in {"approved", "proven"}:
                reason = (
                    "trust_revoked"
                    if any("revoked" in item for item in trust.reasons)
                    else "trust_not_playback_eligible"
                )
                return await self._record_terminal(
                    client_event_id=client_event_id,
                    provider=provider,
                    provider_id=provider_id,
                    source=source,
                    candidate=candidate,
                    status="suppressed",
                    reason=reason,
                    trust_state=trust.state,
                    mode=mode or None,
                )

            preflight = await self._runtime_preflight()
            if preflight["reason"] is not None:
                return await self._record_terminal(
                    client_event_id=client_event_id,
                    provider=provider,
                    provider_id=provider_id,
                    source=source,
                    candidate=candidate,
                    status="suppressed",
                    reason=preflight["reason"],
                    trust_state=trust.state,
                    mode=preflight.get("mode") or mode or None,
                    volume_before=preflight.get("volume_before"),
                    volume_used=preflight.get("volume_used"),
                )

            claimed, duplicate = await self._insert(
                client_event_id=client_event_id,
                provider=provider,
                provider_id=provider_id,
                source=source,
                candidate=candidate,
                status="pending",
                reason="execution_claimed",
                trust_state=trust.state,
                mode=preflight["mode"],
                volume_before=preflight["volume_before"],
                volume_used=preflight["volume_used"],
            )
            if duplicate:
                self._validate_retry_identity(claimed, provider, provider_id)
                return self._row_result(claimed, duplicate=True)

            # Trust/capability are authority too, not preview metadata. Re-read
            # them after the durable claim so a revoke or provider-capability
            # loss cannot ride stale evidence. Provider lookup may take network
            # time, therefore the final live ownership/lifecycle preflight runs
            # *after* this refresh and immediately before device I/O.
            refreshed = await self._catalog.get_by_identity(provider, provider_id)
            if (
                refreshed is None
                or not refreshed.playback_capable
                or refreshed.playback_adapter != _SUPPORTED_ADAPTER
            ):
                row = await self._complete(
                    client_event_id,
                    status="suppressed",
                    reason="candidate_changed_before_play",
                )
                return self._row_result(row)
            fresh_trust, fresh_trust_error = await self._resolve_trust(
                refreshed, mode=preflight["mode"],
            )
            if fresh_trust_error is not None:
                row = await self._complete(
                    client_event_id, status="suppressed", reason=fresh_trust_error
                )
                return self._row_result(row)
            if (
                not fresh_trust.playback_eligible
                or fresh_trust.state not in {"approved", "proven"}
            ):
                reason = (
                    "trust_revoked"
                    if any("revoked" in item for item in fresh_trust.reasons)
                    else "trust_changed_before_play"
                )
                row = await self._complete(
                    client_event_id,
                    status="suppressed",
                    reason=reason,
                )
                return self._row_result(row)
            candidate = refreshed
            trust = fresh_trust

            # Final live authority read after every potentially slow provider/DB
            # operation. Manual Sonos ownership or a lifecycle transition wins.
            live = await self._runtime_preflight()
            if live["reason"] is not None:
                row = await self._complete(
                    client_event_id,
                    status="suppressed",
                    reason=live["reason"],
                    mode=live.get("mode") or preflight["mode"],
                    volume_before=live.get("volume_before"),
                    volume_used=live.get("volume_used"),
                )
                return self._row_result(row)

            if live["mode"] != preflight["mode"]:
                row = await self._complete(
                    client_event_id,
                    status="suppressed",
                    reason="activity_changed_before_play",
                    mode=live["mode"],
                    volume_before=live.get("volume_before"),
                    volume_used=live.get("volume_used"),
                )
                return self._row_result(row)

            sonos = self._app_state.sonos
            mapper = getattr(self._app_state, "music_mapper", None)
            if mapper is None:
                row = await self._complete(
                    client_event_id, status="failed", reason="music_mapper_unavailable"
                )
                return self._row_result(row)

            post_enqueue_guard: dict[str, Any] | None = None

            async def _before_play() -> dict[str, Any]:
                nonlocal post_enqueue_guard
                post_enqueue_guard = await self._runtime_preflight(
                    expected_queue_size=int(live["queue_size"]) + 1,
                    allowed_loaded_provider_id=candidate.provider_id,
                )
                if (
                    post_enqueue_guard.get("reason") is None
                    and post_enqueue_guard.get("mode") != live["mode"]
                ):
                    post_enqueue_guard = {
                        **post_enqueue_guard,
                        "reason": "activity_changed_before_play",
                    }
                return post_enqueue_guard

            try:
                success = await mapper.play_verified_candidate(
                    candidate,
                    expected_queue_size=int(live["queue_size"]),
                    before_play=_before_play,
                )
            except Exception:
                success = False
            if not success:
                failure_reason = "playback_failed"
                if post_enqueue_guard and post_enqueue_guard.get("reason"):
                    failure_reason = f"preplay_{post_enqueue_guard['reason']}"
                else:
                    try:
                        failed_queue = await sonos.get_queue_context()
                        if (
                            failed_queue.get("available")
                            and int(failed_queue.get("queue_size") or 0)
                            != int(live["queue_size"])
                        ):
                            failure_reason = "playback_failed_queue_changed"
                    except Exception:
                        failure_reason = "playback_failed_queue_unknown"
                row = await self._complete(
                    client_event_id, status="failed", reason=failure_reason
                )
                return self._row_result(row)

            final_context = post_enqueue_guard or live
            row = await self._complete_played_with_learning(
                client_event_id,
                candidate_title=candidate.title,
                mode=str(final_context["mode"]),
                volume=int(final_context["volume_used"]),
            )
            result = self._row_result(row)
            result["candidate"] = candidate.to_dict()
            result["trust"] = trust.to_dict()
            return result

    async def _resolve_trust(
        self, candidate: VerifiedMusicCandidate, *, mode: str | None,
    ) -> tuple[Any | None, str | None]:
        try:
            snapshot = await self._taste_provider.snapshot()
            match = snapshot.classify_candidate(
                candidate, mode=None if mode in {None, "", "general"} else mode,
            )
            latest = await self._approval_service.latest_actions([candidate])
        except Exception:
            return None, "trust_authority_unavailable"
        action = latest.get((candidate.provider, candidate.provider_id))
        return self._trust_policy.decide(
            candidate, match, approval_action=action,
        ), None

    async def _runtime_preflight(
        self, *, expected_queue_size: int | None = None,
        allowed_loaded_provider_id: str | None = None,
    ) -> dict[str, Any]:
        automation = getattr(self._app_state, "automation", None)
        away_manager = getattr(self._app_state, "away_manager", None)
        sonos = getattr(self._app_state, "sonos", None)
        tts = getattr(self._app_state, "tts", None)
        ambient = getattr(self._app_state, "ambient_sound", None)
        if any(item is None for item in (automation, away_manager, sonos, tts, ambient)):
            return {"reason": "authority_unavailable"}

        lifecycle = self._lifecycle_state()
        if lifecycle.get("travel"):
            return {"reason": "travel_mode_active"}
        if lifecycle.get("returning_home"):
            return {"reason": "returning_home_active"}
        if bool(getattr(away_manager, "away", False)):
            return {"reason": "apartment_away"}

        mode = str(getattr(automation, "current_mode", "") or "").strip().casefold()
        if not mode:
            return {"reason": "activity_mode_unavailable"}
        if mode == "sleeping":
            return {"reason": "sleeping_active", "mode": mode}
        try:
            if automation.is_dnd_active():
                return {"reason": "dnd_active", "mode": mode}
        except Exception:
            return {"reason": "dnd_authority_unavailable", "mode": mode}
        if bool(getattr(tts, "is_speaking", False)):
            return {"reason": "tts_active", "mode": mode}

        try:
            ambient_state = ambient.get_state()
        except Exception:
            return {"reason": "ambient_authority_unavailable", "mode": mode}
        if (
            ambient_state.get("playing")
            or ambient_state.get("sonos_ambient_active")
            or ambient_state.get("sonos_ambient_pending")
        ):
            return {"reason": "ambient_playback_owned", "mode": mode}

        if not bool(getattr(sonos, "connected", False)) or bool(
            getattr(sonos, "breaker_open", False)
        ):
            return {"reason": "sonos_unavailable", "mode": mode}
        try:
            status = await sonos.get_status()
        except Exception:
            return {"reason": "sonos_status_unavailable", "mode": mode}
        state = str(status.get("state") or "").upper()
        track = str(status.get("track") or "").strip()
        if state not in _IDLE_STATES:
            return {"reason": "sonos_busy", "mode": mode}
        if track:
            if not allowed_loaded_provider_id:
                return {"reason": "sonos_busy", "mode": mode}
            try:
                loaded_uri = await sonos.get_current_media_uri()
            except Exception:
                loaded_uri = None
            if not self._loaded_track_matches_provider(
                loaded_uri, allowed_loaded_provider_id,
            ):
                return {"reason": "sonos_busy", "mode": mode}
        if bool(status.get("mute")):
            return {"reason": "sonos_muted", "mode": mode}

        try:
            queue = await sonos.get_queue_context()
        except Exception:
            return {"reason": "queue_context_unavailable", "mode": mode}
        if not queue.get("available"):
            return {"reason": "queue_context_unavailable", "mode": mode}
        if str(queue.get("play_mode") or "").upper() != "NORMAL":
            return {"reason": "sonos_play_mode_owned", "mode": mode}
        queue_size = int(queue.get("queue_size") or 0)
        if expected_queue_size is not None and queue_size != expected_queue_size:
            return {"reason": "sonos_queue_changed", "mode": mode}

        try:
            current_volume = int(status.get("volume", 0))
            config = await self._setting_loader(MODE_VOLUME_CURVES_KEY) or {}
            period = automation._get_time_period()
            volume_decision = compute_mode_volume(
                mode,
                time_period=period,
                dnd=False,
                current_volume=current_volume,
                config=config,
            )
        except Exception:
            return {"reason": "volume_policy_unavailable", "mode": mode}
        if volume_decision.reason == "no_curve":
            return {"reason": "volume_policy_unavailable", "mode": mode}
        volume_limit = int(volume_decision.target)
        if current_volume <= 0:
            return {
                "reason": "sonos_volume_zero",
                "mode": mode,
                "volume_before": current_volume,
                "volume_used": current_volume,
            }
        if current_volume > volume_limit:
            return {
                "reason": "sonos_volume_above_policy",
                "mode": mode,
                "volume_before": current_volume,
                "volume_used": None,
            }
        return {
            "reason": None,
            "mode": mode,
            "volume_before": current_volume,
            "volume_used": current_volume,
            "queue_size": queue_size,
        }

    @staticmethod
    def _loaded_track_matches_provider(
        uri: str | None, provider_id: str | None,
    ) -> bool:
        """Allow only the exact ShareLink item prepared by this request.

        Sonos exposes the newly appended Apple item as the current stopped track
        before playback begins. That is expected ownership, not unrelated manual
        playback. The URI must still carry the exact Apple ``song:<provider_id>``
        identity; missing or different URIs fail closed.
        """
        provider_id = str(provider_id or "").strip()
        uri = str(uri or "").strip()
        if not provider_id.isdigit() or not uri:
            return False
        decoded = unquote(uri)
        media_part = decoded.split("?", 1)[0]
        return media_part.endswith(f"song:{provider_id}")

    async def _load(self, client_event_id: str) -> MusicAssistedPlaybackEvent | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(MusicAssistedPlaybackEvent).where(
                    MusicAssistedPlaybackEvent.client_event_id == client_event_id
                )
            )
            return result.scalar_one_or_none()

    async def _record_terminal(self, **kwargs: Any) -> dict[str, Any]:
        row, duplicate = await self._insert(**kwargs)
        return self._row_result(row, duplicate=duplicate)

    async def _insert(
        self,
        *,
        client_event_id: str,
        provider: str,
        provider_id: str,
        source: str,
        status: str,
        reason: str,
        candidate: VerifiedMusicCandidate | None = None,
        trust_state: str | None = None,
        mode: str | None = None,
        volume_before: int | None = None,
        volume_used: int | None = None,
    ) -> tuple[MusicAssistedPlaybackEvent, bool]:
        row = MusicAssistedPlaybackEvent(
            client_event_id=client_event_id,
            provider=provider,
            provider_id=provider_id,
            title=candidate.title if candidate is not None else None,
            playback_adapter=(
                candidate.playback_adapter if candidate is not None else None
            ),
            source=source,
            status=status,
            reason=reason,
            trust_state=trust_state,
            mode_at_time=mode,
            volume_before=volume_before,
            volume_used=volume_used,
            completed_at=(
                None if status == "pending" else datetime.now(timezone.utc)
            ),
        )
        async with self._session_factory() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(MusicAssistedPlaybackEvent).where(
                        MusicAssistedPlaybackEvent.client_event_id == client_event_id
                    )
                )
                existing = result.scalar_one()
                return existing, True
            await session.refresh(row)
            return row, False

    async def _complete_played_with_learning(
        self, client_event_id: str, *, candidate_title: str, mode: str, volume: int,
    ) -> MusicAssistedPlaybackEvent:
        """Atomically persist played completion plus canonical Sonos evidence."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(MusicAssistedPlaybackEvent).where(
                    MusicAssistedPlaybackEvent.client_event_id == client_event_id
                )
            )
            row = result.scalar_one()
            if row.status != "played":
                session.add(SonosPlaybackEvent(
                    event_type="play", favorite_title=candidate_title,
                    mode_at_time=mode, volume=volume, triggered_by="manual",
                ))
                row.status = "played"
                row.reason = "explicit_approved_candidate"
                row.mode_at_time = mode
                row.volume_before = volume
                row.volume_used = volume
                row.completed_at = datetime.now(timezone.utc)
                await session.commit()
                await session.refresh(row)
            return row

    async def _complete(
        self,
        client_event_id: str,
        *,
        status: str,
        reason: str,
        mode: str | None = None,
        volume_before: int | None = None,
        volume_used: int | None = None,
    ) -> MusicAssistedPlaybackEvent:
        async with self._session_factory() as session:
            result = await session.execute(
                select(MusicAssistedPlaybackEvent).where(
                    MusicAssistedPlaybackEvent.client_event_id == client_event_id
                )
            )
            row = result.scalar_one()
            row.status = status
            row.reason = reason
            if mode is not None:
                row.mode_at_time = mode
            if volume_before is not None:
                row.volume_before = volume_before
            if volume_used is not None:
                row.volume_used = volume_used
            row.completed_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(row)
            return row

    @staticmethod
    def _validate_retry_identity(
        row: MusicAssistedPlaybackEvent, provider: str, provider_id: str,
    ) -> None:
        if row.provider != provider or row.provider_id != provider_id:
            raise ValueError("client_event_id already used for a different candidate")

    @staticmethod
    def _row_result(
        row: MusicAssistedPlaybackEvent, *, duplicate: bool = False,
    ) -> dict[str, Any]:
        return {
            "status": row.status,
            "reason": row.reason,
            "duplicate": duplicate,
            "explicit_only": True,
            "client_event_id": row.client_event_id,
            "provider": row.provider,
            "provider_id": row.provider_id,
            "title": row.title,
            "playback_adapter": row.playback_adapter,
            "source": row.source,
            "trust_state": row.trust_state,
            "mode": row.mode_at_time,
            "volume_before": row.volume_before,
            "volume_used": row.volume_used,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "completed_at": (
                row.completed_at.isoformat() if row.completed_at else None
            ),
        }
