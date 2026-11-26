from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services.music_discovery import DiscoveryTrack
from backend.services.music_requests import MusicRequest, MusicRequestResolver, MusicRequestResult
from backend.services.music_session_plan import MusicSessionPlanner
from backend.services.playlist_catalog import VerifiedMusicCandidate


def candidate(identity):
    url = f"https://music.apple.com/us/song/example/{identity}"
    return VerifiedMusicCandidate(
        provider="itunes_search", provider_id=identity, media_type="track",
        title=f"Track {identity}", uri=url, source="itunes_search+sonos_share_link",
        playback_capability="supported", playback_adapter="sonos_apple_music_share_link",
        playback_reference=url,
        metadata={"artist_name": "Synthetic artist", "apple_music_canonical": f"song:{identity}",
                  "playback_verification": "live_verified"},
    )


def track(identity, **kwargs):
    values = dict(
        provider="itunes_search", provider_id=identity, catalog_verified=True,
        playback_capability="supported", playback_adapter="sonos_apple_music_share_link",
        playback_reference=candidate(identity).uri, playback_reason="provider_exact_match",
        artist_name="Synthetic artist", track_name=f"Track {identity}", album_name=None,
        preview_url=None, artwork_url=None, external_url=None,
        taste_classification="exploratory", taste_preference=0, taste_sources=(),
    )
    return DiscoveryTrack(**(values | kwargs))


def request(kind, tracks=(), familiar=()):
    resolved = MusicRequestResolver().resolve(MusicRequest(kind=kind))
    discovery = SimpleNamespace(
        shadow=True, actuation_allowed=False,
        clusters=(SimpleNamespace(tracks=tracks),), generated_at=datetime.now(timezone.utc),
    )
    return MusicRequestResult("shadow_ready", resolved, familiar, discovery)


class FakeCatalog:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    async def get_by_identity(self, provider, identity):
        self.calls.append((provider, identity))
        return self.candidates.get(identity)


class FakeTaste:
    def __init__(self, classes=None, fail=False):
        self.classes = classes or {}
        self.fail = fail

    async def snapshot(self):
        if self.fail:
            raise RuntimeError("unavailable")
        return self

    def classify_candidate(self, item, *, mode):
        classification, preference = self.classes.get(item.provider_id, ("exploratory", 0))
        return SimpleNamespace(classification=classification, preference=preference)


class FakeApprovals:
    def __init__(self, actions=None, fail=False):
        self.actions = actions or {}
        self.fail = fail

    async def latest_actions(self, candidates):
        if self.fail:
            raise RuntimeError("unavailable")
        return {("itunes_search", key): value for key, value in self.actions.items()}


def planner(catalog, taste=None, approvals=None):
    return MusicSessionPlanner(
        catalog=catalog, taste_provider=taste or FakeTaste(),
        approval_service=approvals or FakeApprovals(),
    )


@pytest.mark.asyncio
async def test_unapproved_discovery_can_be_planned_without_actuation():
    c = FakeCatalog({"10001": candidate("10001")})
    result = await planner(c).preview(request("discovery", (track("10001"),)), count=1)
    assert result.to_dict()["status"] == "preview_ready"
    assert result.to_dict()["actuation_allowed"] is False
    assert result.to_dict()["shadow"] is True
    assert result.tracks[0].candidate.provider_id == "10001"


@pytest.mark.asyncio
async def test_deduplication_and_exact_identity_and_supported_adapter():
    c = FakeCatalog({"10001": candidate("10001"), "10002": candidate("10003"),
                     "10003": candidate("10003")})
    result = await planner(c).preview(request("discovery", (
        track("10001"), track("10001"), track("10002"),
        track("10003", playback_capability="unsupported"),
    )), count=3)
    assert [x.candidate.provider_id for x in result.tracks] == ["10001"]
    assert len(c.calls) == 2
    assert result.reason == "eligible_track_shortfall"


@pytest.mark.asyncio
async def test_revoked_rejected_and_negative_tracks_excluded():
    ids = ("10001", "10002", "10003", "10004")
    c = FakeCatalog({i: candidate(i) for i in ids})
    p = planner(c, FakeTaste({"10002": ("rejected", -0.8), "10003": ("exploratory", -0.1)}),
                FakeApprovals({"10001": "revoke", "10002": "approve"}))
    result = await p.preview(request("discovery", tuple(track(i) for i in ids)))
    assert [x.candidate.provider_id for x in result.tracks] == ["10004"]


@pytest.mark.asyncio
@pytest.mark.parametrize("taste,approvals", [
    (FakeTaste(fail=True), FakeApprovals()),
    (FakeTaste(), FakeApprovals(fail=True)),
])
async def test_missing_authority_abstains(taste, approvals):
    c = FakeCatalog({"10001": candidate("10001")})
    result = await planner(c, taste, approvals).preview(request("discovery", (track("10001"),)))
    assert not result.tracks
    assert result.reason == "taste_or_approval_unavailable"


@pytest.mark.asyncio
async def test_familiar_does_not_substitute_novelty_or_favorite_container():
    good = candidate("10001")
    c = FakeCatalog({"10001": good, "10002": candidate("10002")})
    suggestions = (SimpleNamespace(candidate=good),
                   SimpleNamespace(candidate=replace(candidate("10003"), media_type="favorite")))
    result = await planner(c, FakeTaste({"10001": ("familiar", 0.4)})).preview(
        request("familiar", (track("10002"),), suggestions), count=2)
    assert [x.candidate.provider_id for x in result.tracks] == ["10001"]


@pytest.mark.asyncio
async def test_bounded_lookup_and_track_budget():
    ids = [str(i) for i in range(10000, 10040)]
    c = FakeCatalog({i: candidate(i) for i in ids})
    p = planner(c)
    result = await p.preview(request("discovery", tuple(track(i) for i in ids)))
    assert len(c.calls) == 30
    assert len(result.tracks) == 5
    for value in (0, 7, True, 1.5):
        with pytest.raises(ValueError):
            await p.preview(request("discovery"), count=value)
