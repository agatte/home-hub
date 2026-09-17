from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import MusicApprovalEvent
from backend.services.music_requests import MusicRequestService
from backend.services.music_taste import CandidateTasteMatch
from backend.services.music_trust import MusicApprovalService, MusicTrustPolicy
from backend.services.playlist_catalog import VerifiedMusicCandidate


def _match(classification: str) -> CandidateTasteMatch:
    return CandidateTasteMatch(
        classification=classification,
        familiarity=1.0 if classification in {"familiar", "proven"} else 0.0,
        preference=0.6 if classification in {"familiar", "proven"} else -0.7 if classification == "rejected" else 0.0,
        artist_depth=0,
        positive_weight=2.0 if classification == "proven" else 0.0,
        negative_weight=2.0 if classification == "rejected" else 0.0,
        sources=("test",),
    )


def _candidate(*, playable: bool = True, provider_id: str = "fav-1") -> VerifiedMusicCandidate:
    return VerifiedMusicCandidate(
        provider="sonos_favorite", provider_id=provider_id, media_type="favorite",
        title="Road Trip Favorites", uri="sonos://fav-1", source="favorite",
        catalog_verified=True,
        playback_capability="supported" if playable else "metadata_only",
        playback_adapter="sonos_favorite_title" if playable else None,
        playback_reference="Road Trip Favorites" if playable else None,
    )


async def _make_service():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory, MusicApprovalService(session_factory=factory)


def test_policy_requires_capability_for_approval_eligibility():
    decision = MusicTrustPolicy().decide(
        _candidate(playable=False), _match("familiar"), approval_action="approve",
    )
    assert decision.state == "suggestion_only"
    assert decision.playback_eligible is False
    assert decision.explicit_approval is True
    assert "no currently supported playback" in decision.reasons[0]


def test_policy_single_click_approves_but_does_not_make_candidate_proven():
    decision = MusicTrustPolicy().decide(
        _candidate(), _match("familiar"), approval_action="approve",
    )
    assert decision.state == "approved"
    assert decision.playback_eligible is True
    assert decision.explicit_approval is True


def test_policy_proven_requires_independent_taste_evidence():
    policy = MusicTrustPolicy()
    approved = policy.decide(_candidate(), _match("familiar"), approval_action="approve")
    proven = policy.decide(_candidate(), _match("proven"), approval_action=None)
    assert approved.state == "approved"
    assert proven.state == "proven"
    assert proven.playback_eligible is True
    assert proven.explicit_approval is False
    assert "independently" in proven.reasons[0]


def test_policy_rejection_and_revocation_demote_safely():
    policy = MusicTrustPolicy()
    rejected = policy.decide(_candidate(), _match("rejected"), approval_action="approve")
    revoked = policy.decide(_candidate(playable=False), None, approval_action="revoke")
    assert rejected.state == "suggestion_only"
    assert rejected.playback_eligible is False
    assert "rejects" in rejected.reasons[0]
    assert revoked.state == "suggestion_only"
    assert revoked.playback_eligible is False
    assert revoked.explicit_approval is False
    assert revoked.reasons == ("explicit approval was revoked",)


@pytest.mark.asyncio
async def test_approval_ledger_is_idempotent_and_preserves_revocation_history():
    engine, factory, service = await _make_service()
    candidate = _candidate()
    try:
        first, duplicate = await service.record(
            client_event_id="approval-1", action="approve",
            candidate=candidate, source="test",
        )
        retry, retry_duplicate = await service.record(
            client_event_id="approval-1", action="approve",
            candidate=candidate, source="test",
        )
        revoked, revoked_duplicate = await service.record(
            client_event_id="approval-2", action="revoke",
            candidate=candidate, source="test",
        )
        latest = await service.latest_actions([candidate])
        async with factory() as session:
            count = await session.scalar(select(func.count()).select_from(MusicApprovalEvent))
    finally:
        await engine.dispose()

    assert duplicate is False
    assert retry_duplicate is True
    assert revoked_duplicate is False
    assert retry["id"] == first["id"]
    assert revoked["action"] == "revoke"
    assert count == 2
    assert latest[(candidate.provider, candidate.provider_id)] == "revoke"


@pytest.mark.asyncio
async def test_approval_requires_verified_playback_capability():
    engine, _, service = await _make_service()
    try:
        with pytest.raises(ValueError, match="verified and playback-capable"):
            await service.record(
                client_event_id="approval-unsupported",
                action="approve",
                candidate=_candidate(playable=False),
                source="test",
            )
        unverified = VerifiedMusicCandidate(
            provider="sonos_favorite", provider_id="fav-unverified", media_type="favorite",
            title="Unverified", uri="sonos://unverified", source="test",
            verified=False, catalog_verified=True, playback_capability="supported",
            playback_adapter="sonos_favorite_title", playback_reference="Unverified",
        )
        with pytest.raises(ValueError, match="verified and playback-capable"):
            await service.record(
                client_event_id="approval-unverified", action="approve",
                candidate=unverified, source="test",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_latest_record_retains_exact_candidate_snapshot_for_future_revocation():
    engine, _, service = await _make_service()
    candidate = _candidate(provider_id="fav-history")
    try:
        await service.record(
            client_event_id="approval-history", action="approve",
            candidate=candidate, source="test",
        )
        latest = await service.latest_record(
            provider=candidate.provider, provider_id=candidate.provider_id,
        )
    finally:
        await engine.dispose()

    assert latest is not None
    assert latest["action"] == "approve"
    assert latest["provider_id"] == "fav-history"
    assert latest["playback_adapter"] == "sonos_favorite_title"
    assert latest["playback_reference"] == "Road Trip Favorites"


class _Catalog:
    available = True

    def __init__(self, candidates):
        self.candidates = candidates

    async def search(self, intent, *, limit=12):
        del intent
        return self.candidates[:limit]


class _Snapshot:
    def classify_candidate(self, candidate, *, mode=None):
        del candidate, mode
        return _match("familiar")


class _Taste:
    async def snapshot(self):
        return _Snapshot()


class _Discovery:
    enabled = False


def _request_service(*, catalog, approval):
    return MusicRequestService(
        app_state=SimpleNamespace(automation=SimpleNamespace(current_mode="working")),
        catalog=catalog,
        taste_provider=_Taste(),
        discovery=_Discovery(),
        approval_service=approval,
    )


@pytest.mark.asyncio
async def test_request_service_retry_of_old_approval_respects_newer_revocation():
    engine, _, approval = await _make_service()
    candidate = _candidate()
    catalog = _Catalog([candidate])
    service = _request_service(catalog=catalog, approval=approval)
    try:
        approved = await service.record_trust_event(
            client_event_id="event-approve", action="approve",
            provider=candidate.provider, provider_id=candidate.provider_id, source="test",
        )
        revoked = await service.record_trust_event(
            client_event_id="event-revoke", action="revoke",
            provider=candidate.provider, provider_id=candidate.provider_id, source="test",
        )
        retry = await service.record_trust_event(
            client_event_id="event-approve", action="approve",
            provider=candidate.provider, provider_id=candidate.provider_id, source="test",
        )
    finally:
        await engine.dispose()

    assert approved["trust"]["state"] == "approved"
    assert revoked["trust"]["state"] == "suggestion_only"
    assert retry["duplicate"] is True
    assert retry["current_approval_action"] == "revoke"
    assert retry["trust"]["state"] == "suggestion_only"


@pytest.mark.asyncio
async def test_request_service_can_revoke_after_candidate_leaves_live_catalog():
    engine, _, approval = await _make_service()
    candidate = _candidate(provider_id="fav-gone")
    catalog = _Catalog([candidate])
    service = _request_service(catalog=catalog, approval=approval)
    try:
        await service.record_trust_event(
            client_event_id="gone-approve", action="approve",
            provider=candidate.provider, provider_id=candidate.provider_id, source="test",
        )
        catalog.candidates = []
        result = await service.record_trust_event(
            client_event_id="gone-revoke", action="revoke",
            provider=candidate.provider, provider_id=candidate.provider_id, source="test",
        )
    finally:
        await engine.dispose()

    assert result["current_approval_action"] == "revoke"
    assert result["trust"]["state"] == "suggestion_only"
    assert result["trust"]["playback_eligible"] is False
    assert result["candidate"]["catalog_verified"] is False
    assert result["actuation_allowed"] is False
