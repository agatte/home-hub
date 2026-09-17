from types import SimpleNamespace

import pytest

from backend.services.music_requests import (
    MusicRequest,
    MusicRequestResolver,
    MusicRequestService,
)
from backend.services.music_taste import CandidateTasteMatch
from backend.services.playlist_catalog import VerifiedMusicCandidate


def _match(classification, preference=0.0):
    return CandidateTasteMatch(
        classification=classification,
        familiarity=1.0 if classification in {"familiar", "proven"} else 0.0,
        preference=preference,
        artist_depth=0,
        positive_weight=2.0 if classification == "proven" else 0.0,
        negative_weight=2.0 if classification == "rejected" else 0.0,
        sources=("test",),
    )


def _favorite(title):
    return VerifiedMusicCandidate(
        provider="sonos_favorite", provider_id=title.lower(), media_type="favorite",
        title=title, uri=f"x-rincon-cpcontainer:{title}", source="favorite",
        catalog_verified=True, playback_capability="supported",
        playback_adapter="sonos_favorite_title", playback_reference=title,
        metadata={},
    )


class FakeSnapshot:
    def __init__(self, matches):
        self.matches = matches

    def classify_candidate(self, candidate, *, mode=None):
        del mode
        return self.matches.get(candidate.title, _match("exploratory"))


class FakeTaste:
    def __init__(self, snapshot):
        self.current = snapshot
        self.calls = 0

    async def snapshot(self):
        self.calls += 1
        if isinstance(self.current, Exception):
            raise self.current
        return self.current


class FakeCatalog:
    available = True

    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = []

    async def search(self, intent, *, limit=12):
        self.calls.append((intent, limit))
        return self.candidates[:limit]


class FakeDiscovery:
    enabled = True

    def __init__(self):
        self.calls = []
        self.result = SimpleNamespace(
            status="shadow_ready",
            clusters=(object(),),
            to_dict=lambda: {"status": "shadow_ready", "clusters": [{"artist_name": "New Artist"}]},
        )

    async def preview(self, mode, *, policy="gentle", count=6, tracks_per_artist=3, intent=None):
        self.calls.append({
            "mode": mode,
            "policy": policy,
            "count": count,
            "tracks_per_artist": tracks_per_artist,
            "intent": intent,
        })
        return self.result


def _service(*, matches=None, candidates=None, current_mode="working"):
    taste = FakeTaste(FakeSnapshot(matches or {}))
    catalog = FakeCatalog(candidates or [])
    discovery = FakeDiscovery()
    app_state = SimpleNamespace(automation=SimpleNamespace(current_mode=current_mode))
    return MusicRequestService(
        app_state=app_state,
        catalog=catalog,
        taste_provider=taste,
        discovery=discovery,
    ), taste, catalog, discovery


def test_resolver_understands_strict_familiar_request():
    resolved = MusicRequestResolver().resolve(
        MusicRequest(request_text="Play something familiar", source="test"),
        current_mode="gaming",
    )
    assert resolved.kind == "familiar"
    assert resolved.mode == "gaming"
    assert resolved.policy == "gentle"
    assert resolved.familiarity_target == 1.0
    assert resolved.novelty_target == 0.0
    assert resolved.semantic_request is None


def test_resolver_understands_explicit_new_music_request():
    resolved = MusicRequestResolver().resolve(
        MusicRequest(request_text="Play new music"),
        current_mode="social",
    )
    assert resolved.kind == "discovery"
    assert resolved.policy == "explore"
    assert resolved.novelty_target == 0.8
    assert resolved.semantic_request is None


def test_resolver_maps_natural_mood_phrase_to_existing_semantic_preset():
    resolved = MusicRequestResolver().resolve(
        MusicRequest(request_text="I'm feeling energetic"),
        current_mode="working",
    )
    assert resolved.kind == "mood"
    assert resolved.semantic_key == "energetic"
    assert "energetic" in resolved.semantic_concepts
    assert resolved.familiarity_target == 0.8
    assert resolved.novelty_target == 0.2


def test_resolver_rejects_conflicting_familiar_and_new_directives():
    with pytest.raises(ValueError, match="both familiar and new music"):
        MusicRequestResolver().resolve(
            MusicRequest(request_text="Play something familiar and new music"),
            current_mode="working",
        )


def test_resolver_supports_structured_kind_and_pregameday_alias():
    resolved = MusicRequestResolver().resolve(
        MusicRequest(kind="discovery", mode="pregameday", semantic_request="energetic"),
    )
    assert resolved.kind == "discovery"
    assert resolved.mode == "gameday"
    assert resolved.semantic_key == "energetic"


@pytest.mark.asyncio
async def test_familiar_request_returns_only_proven_or_familiar_candidates():
    candidates = [_favorite("Known One"), _favorite("Unknown One"), _favorite("Rejected One")]
    service, taste, catalog, discovery = _service(
        candidates=candidates,
        matches={
            "Known One": _match("proven", 0.8),
            "Unknown One": _match("exploratory", 0.5),
            "Rejected One": _match("rejected", -0.8),
        },
    )
    result = await service.preview(MusicRequest(request_text="play something familiar"), count=6)
    assert result.status == "shadow_ready"
    assert [item.candidate.title for item in result.familiar_suggestions] == ["Known One"]
    assert result.discovery is None
    assert taste.calls == 1
    assert len(catalog.calls) == 1
    assert discovery.calls == []


@pytest.mark.asyncio
async def test_new_music_request_uses_only_bounded_discovery_lane():
    service, taste, catalog, discovery = _service(candidates=[_favorite("Known")])
    result = await service.preview(MusicRequest(request_text="play new music"), count=6)
    assert result.status == "shadow_ready"
    assert result.familiar_suggestions == ()
    assert taste.calls == 0
    assert catalog.calls == []
    assert discovery.calls == [{
        "mode": "working", "policy": "explore", "count": 6,
        "tracks_per_artist": 3, "intent": None,
    }]


@pytest.mark.asyncio
async def test_mood_request_targets_five_familiar_to_one_discovery_at_six_results():
    candidates = [_favorite(f"Known {index}") for index in range(1, 7)]
    matches = {candidate.title: _match("familiar", 0.4) for candidate in candidates}
    service, _, _, discovery = _service(candidates=candidates, matches=matches)
    result = await service.preview(MusicRequest(request_text="I'm feeling energetic"), count=6)
    assert len(result.familiar_suggestions) == 5
    assert discovery.calls == [{
        "mode": "working", "policy": "gentle", "count": 1,
        "tracks_per_artist": 3, "intent": "I'm feeling energetic",
    }]
    payload = result.to_dict()
    assert payload["resolved_request"]["semantic_key"] == "energetic"
    assert payload["actuation_allowed"] is False


@pytest.mark.asyncio
async def test_request_rereads_taste_so_feedback_can_change_familiar_ordering():
    first, second = _favorite("First"), _favorite("Second")
    service, taste, _, _ = _service(
        candidates=[first, second],
        matches={"First": _match("familiar", 0.8), "Second": _match("familiar", 0.1)},
    )
    before = await service.preview(MusicRequest(request_text="something familiar"), count=2)
    assert before.familiar_suggestions[0].candidate.title == "First"

    taste.current = FakeSnapshot({
        "First": _match("familiar", -0.2),
        "Second": _match("proven", 0.9),
    })
    after = await service.preview(MusicRequest(request_text="something familiar"), count=2)
    assert after.familiar_suggestions[0].candidate.title == "Second"
    assert taste.calls == 2


@pytest.mark.asyncio
async def test_familiar_request_abstains_when_taste_snapshot_is_unavailable():
    service, taste, _, discovery = _service(candidates=[_favorite("Known")])
    taste.current = RuntimeError("db unavailable")
    result = await service.preview(MusicRequest(request_text="play familiar music"), count=3)
    assert result.status == "no_candidates"
    assert result.familiar_suggestions == ()
    assert "taste snapshot unavailable" in (result.note or "")
    assert discovery.calls == []


def test_familiar_request_can_carry_a_mood_without_losing_strict_familiarity():
    resolved = MusicRequestResolver().resolve(
        MusicRequest(request_text="play something familiar and energetic"),
        current_mode="gaming",
    )
    assert resolved.kind == "familiar"
    assert resolved.semantic_key == "energetic"
    assert resolved.familiarity_target == 1.0
    assert resolved.novelty_target == 0.0


def test_resolver_rejects_structured_kind_that_conflicts_with_request_language():
    resolver = MusicRequestResolver()
    with pytest.raises(ValueError, match="conflicts"):
        resolver.resolve(MusicRequest(request_text="play new music", kind="familiar"))
    with pytest.raises(ValueError, match="conflicts"):
        resolver.resolve(MusicRequest(request_text="play something familiar", kind="discovery"))
