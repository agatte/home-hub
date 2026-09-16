from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.models import MusicFeedbackEvent
from backend.services.music_feedback import MusicFeedbackService
from backend.services.music_taste import MusicTasteService
from backend.services.playlist_catalog import VerifiedMusicCandidate


async def _make_service():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory, MusicFeedbackService(session_factory=factory)


@pytest.mark.asyncio
async def test_record_is_idempotent_for_same_client_event():
    engine, factory, service = await _make_service()
    payload = dict(
        client_event_id="event-1",
        action="fits_me",
        target_kind="artist",
        artist_name="Wardruna",
        provider="itunes_search",
        provider_id="123",
        mode="gaming",
        policy="explore",
        intent="Valheim",
        source="dashboard:music_discovery",
    )
    try:
        first, first_duplicate = await service.record(**payload)
        second, second_duplicate = await service.record(**payload)
        async with factory() as session:
            count = await session.scalar(select(func.count()).select_from(MusicFeedbackEvent))
    finally:
        await engine.dispose()

    assert first_duplicate is False
    assert second_duplicate is True
    assert first["id"] == second["id"]
    assert count == 1


@pytest.mark.asyncio
async def test_reused_event_id_with_different_feedback_is_rejected():
    engine, _, service = await _make_service()
    base = dict(
        client_event_id="event-2",
        target_kind="artist",
        artist_name="Wardruna",
        provider="itunes_search",
        provider_id="123",
    )
    try:
        await service.record(action="fits_me", **base)
        with pytest.raises(ValueError, match="already used"):
            await service.record(action="not_for_me", **base)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_track_feedback_requires_exact_track_identity():
    engine, _, service = await _make_service()
    try:
        with pytest.raises(ValueError, match="target_track_name"):
            await service.record(
                client_event_id="event-3",
                action="interesting",
                target_kind="track",
                artist_name="Artist",
                provider="itunes_search",
                provider_id="999",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_durable_feedback_flows_into_canonical_taste_snapshot():
    engine, factory, feedback = await _make_service()
    taste = MusicTasteService(session_factory=factory)
    try:
        await feedback.record(
            client_event_id="event-taste-1",
            action="fits_me",
            target_kind="artist",
            artist_name="Wardruna",
            provider="itunes_search",
            provider_id="123",
            mode="gaming",
        )
        snapshot = await taste.snapshot()
    finally:
        await engine.dispose()

    match = snapshot.classify_candidate(
        VerifiedMusicCandidate(
            provider="test",
            provider_id="wardruna",
            media_type="artist",
            title="Wardruna",
            uri="test://verified",
            source="test",
            metadata={"artist_name": "Wardruna"},
        ),
        mode="gaming",
    )
    assert match.classification == "exploratory"
    assert match.familiarity == 0.0
    assert match.preference > 0.7
    assert snapshot.artists["wardruna"].contexts["gaming"].preference > 0.7
