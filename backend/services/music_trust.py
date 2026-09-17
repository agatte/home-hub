from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.database import async_session
from backend.models import MusicApprovalEvent
from backend.services.playlist_catalog import VerifiedMusicCandidate

APPROVAL_ACTIONS = ("approve", "revoke")


@dataclass(frozen=True)
class MusicTrustDecision:
    state: str
    playback_eligible: bool
    explicit_approval: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


class MusicTrustPolicy:
    """Pure policy over capability, taste evidence, and explicit approval."""

    def decide(
        self,
        candidate: VerifiedMusicCandidate,
        taste_match: Any,
        *,
        approval_action: str | None = None,
    ) -> MusicTrustDecision:
        reasons: list[str] = []
        if approval_action == "revoke":
            return MusicTrustDecision(
                state="suggestion_only",
                playback_eligible=False,
                explicit_approval=False,
                reasons=("explicit approval was revoked",),
            )

        capable = bool(
            candidate.verified and candidate.catalog_verified and candidate.playback_capable
        )
        if not capable:
            return MusicTrustDecision(
                state="suggestion_only",
                playback_eligible=False,
                explicit_approval=approval_action == "approve",
                reasons=("no currently supported playback adapter/reference",),
            )

        classification = str(
            getattr(taste_match, "classification", "exploratory") or "exploratory"
        )
        if classification == "rejected":
            return MusicTrustDecision(
                state="suggestion_only",
                playback_eligible=False,
                explicit_approval=approval_action == "approve",
                reasons=("canonical taste currently rejects this exact identity",),
            )
        if classification == "proven":
            reasons.append(
                "canonical taste independently classifies this exact identity as proven"
            )
            if approval_action == "approve":
                reasons.append("explicit approval also present")
            return MusicTrustDecision(
                state="proven",
                playback_eligible=True,
                explicit_approval=approval_action == "approve",
                reasons=tuple(reasons),
            )
        if approval_action == "approve":
            return MusicTrustDecision(
                state="approved",
                playback_eligible=True,
                explicit_approval=True,
                reasons=("explicit approval for this exact provider identity",),
            )
        return MusicTrustDecision(
            state="suggestion_only",
            playback_eligible=False,
            explicit_approval=False,
            reasons=(
                f"taste is {classification}; explicit approval or proven evidence is required",
            ),
        )


class MusicApprovalService:
    """Append-only exact-candidate approval ledger; never actuates playback."""

    def __init__(self, *, session_factory=async_session) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        *,
        client_event_id: str,
        action: str,
        candidate: VerifiedMusicCandidate,
        source: str,
    ) -> tuple[dict[str, Any], bool]:
        client_event_id = client_event_id.strip()
        action = action.strip().casefold()
        source = (source.strip() or "dashboard:music_trust")[:80]
        if not client_event_id or len(client_event_id) > 80:
            raise ValueError("client_event_id is required and must be <= 80 characters")
        if action not in APPROVAL_ACTIONS:
            raise ValueError(f"unsupported approval action: {action}")
        if not candidate.provider or not candidate.provider_id:
            raise ValueError("provider and provider_id are required")
        if action == "approve" and not (
            candidate.verified and candidate.catalog_verified and candidate.playback_capable
        ):
            raise ValueError("candidate is not currently verified and playback-capable")

        values = dict(
            client_event_id=client_event_id,
            action=action,
            provider=candidate.provider,
            provider_id=candidate.provider_id,
            media_type=candidate.media_type,
            title=candidate.title,
            playback_adapter=candidate.playback_adapter,
            playback_reference=candidate.playback_reference,
            source=source,
        )
        async with self._session_factory() as session:
            result = await session.execute(
                select(MusicApprovalEvent).where(MusicApprovalEvent.client_event_id == client_event_id)
            )
            existing = result.scalar_one_or_none()
            if existing is not None:
                if not self._same_event(existing, **values):
                    raise ValueError("client_event_id already used for different approval")
                return self._to_dict(existing), True

            row = MusicApprovalEvent(**values)
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(MusicApprovalEvent).where(MusicApprovalEvent.client_event_id == client_event_id)
                )
                existing = result.scalar_one_or_none()
                if existing is None:
                    raise
                if not self._same_event(existing, **values):
                    raise ValueError("client_event_id already used for different approval")
                return self._to_dict(existing), True
            await session.refresh(row)
            return self._to_dict(row), False

    async def latest_actions(
        self,
        candidates: Iterable[VerifiedMusicCandidate],
    ) -> dict[tuple[str, str], str]:
        keys = {(item.provider, item.provider_id) for item in candidates if item.provider and item.provider_id}
        if not keys:
            return {}
        async with self._session_factory() as session:
            result = await session.execute(
                select(MusicApprovalEvent).order_by(MusicApprovalEvent.created_at, MusicApprovalEvent.id)
            )
            latest: dict[tuple[str, str], str] = {}
            for row in result.scalars():
                key = (row.provider, row.provider_id)
                if key in keys:
                    latest[key] = row.action
            return latest

    async def latest_record(self, *, provider: str, provider_id: str) -> dict[str, Any] | None:
        provider = provider.strip()
        provider_id = provider_id.strip()
        if not provider or not provider_id:
            return None
        async with self._session_factory() as session:
            result = await session.execute(
                select(MusicApprovalEvent)
                .where(
                    MusicApprovalEvent.provider == provider,
                    MusicApprovalEvent.provider_id == provider_id,
                )
                .order_by(MusicApprovalEvent.created_at.desc(), MusicApprovalEvent.id.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return self._to_dict(row) if row is not None else None

    @staticmethod
    def _same_event(row: MusicApprovalEvent, **expected: Any) -> bool:
        return all(getattr(row, key) == value for key, value in expected.items())

    @staticmethod
    def _to_dict(row: MusicApprovalEvent) -> dict[str, Any]:
        return {
            "id": row.id,
            "client_event_id": row.client_event_id,
            "action": row.action,
            "provider": row.provider,
            "provider_id": row.provider_id,
            "media_type": row.media_type,
            "title": row.title,
            "playback_adapter": row.playback_adapter,
            "playback_reference": row.playback_reference,
            "source": row.source,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
