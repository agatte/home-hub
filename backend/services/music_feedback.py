"""Durable explicit feedback for shared Music Intelligence (#263)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.database import async_session
from backend.models import MusicFeedbackEvent

FEEDBACK_ACTIONS = ("fits_me", "interesting", "not_for_me")
FEEDBACK_TARGETS = ("artist", "track")


class MusicFeedbackService:
    """Persists explicit feedback only; never actuates or trains MusicBandit."""

    def __init__(self, *, session_factory=async_session) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        *,
        client_event_id: str,
        action: str,
        target_kind: str,
        artist_name: str,
        provider: str,
        provider_id: str,
        target_track_name: str | None = None,
        mode: str | None = None,
        policy: str | None = None,
        intent: str | None = None,
        source: str = "dashboard:music_discovery",
    ) -> tuple[dict[str, Any], bool]:
        client_event_id = client_event_id.strip()
        action = action.strip().casefold()
        target_kind = target_kind.strip().casefold()
        artist_name = artist_name.strip()
        provider = provider.strip()
        provider_id = provider_id.strip()
        target_track_name = (target_track_name or "").strip() or None
        mode = (mode or "").strip() or None
        policy = (policy or "").strip() or None
        intent = (intent or "").strip() or None
        source = (source.strip() or "dashboard:music_discovery")[:80]

        if not client_event_id or len(client_event_id) > 80:
            raise ValueError("client_event_id is required and must be <= 80 characters")
        if action not in FEEDBACK_ACTIONS:
            raise ValueError(f"unsupported feedback action: {action}")
        if target_kind not in FEEDBACK_TARGETS:
            raise ValueError(f"unsupported feedback target: {target_kind}")
        if not artist_name:
            raise ValueError("artist_name is required")
        if target_kind == "track" and not target_track_name:
            raise ValueError("target_track_name is required for track feedback")
        if not provider or not provider_id:
            raise ValueError("provider and provider_id are required")

        async with self._session_factory() as session:
            result = await session.execute(
                select(MusicFeedbackEvent).where(
                    MusicFeedbackEvent.client_event_id == client_event_id
                )
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                if not self._same_event(
                    existing,
                    action=action,
                    target_kind=target_kind,
                    artist_name=artist_name,
                    target_track_name=target_track_name,
                    provider=provider,
                    provider_id=provider_id,
                    mode=mode,
                    policy=policy,
                    intent=intent,
                    source=source,
                ):
                    raise ValueError("client_event_id already used for different feedback")
                return self._to_dict(existing), True

            row = MusicFeedbackEvent(
                client_event_id=client_event_id,
                action=action,
                target_kind=target_kind,
                artist_name=artist_name,
                target_track_name=target_track_name,
                provider=provider,
                provider_id=provider_id,
                mode=mode,
                policy=policy,
                intent=intent,
                source=source,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(MusicFeedbackEvent).where(
                        MusicFeedbackEvent.client_event_id == client_event_id
                    )
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    raise
                if not self._same_event(
                    existing,
                    action=action,
                    target_kind=target_kind,
                    artist_name=artist_name,
                    target_track_name=target_track_name,
                    provider=provider,
                    provider_id=provider_id,
                    mode=mode,
                    policy=policy,
                    intent=intent,
                    source=source,
                ):
                    raise ValueError("client_event_id already used for different feedback")
                return self._to_dict(existing), True
            await session.refresh(row)
            return self._to_dict(row), False

    @staticmethod
    def _same_event(row: MusicFeedbackEvent, **expected: Any) -> bool:
        return all(getattr(row, key) == value for key, value in expected.items())

    @staticmethod
    def _to_dict(row: MusicFeedbackEvent) -> dict[str, Any]:
        return {
            "id": row.id,
            "client_event_id": row.client_event_id,
            "action": row.action,
            "target_kind": row.target_kind,
            "artist_name": row.artist_name,
            "target_track_name": row.target_track_name,
            "provider": row.provider,
            "provider_id": row.provider_id,
            "mode": row.mode,
            "policy": row.policy,
            "intent": row.intent,
            "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
