from types import SimpleNamespace

import pytest

from backend.services.playlist_catalog import (
    AppleMusicShareCatalog,
    CompositeMusicCatalog,
    SonosFavoritesCatalog,
    VerifiedMusicCandidate,
)


def _sonos(*, connected=True, household_id="HH-TEST"):
    return SimpleNamespace(
        connected=connected,
        device=SimpleNamespace(household_id=household_id),
    )


def _track(
    provider_id="1713833576",
    *,
    artist="AJR",
    title="Bang!",
    url=None,
):
    return {
        "provider": "itunes_search",
        "provider_id": provider_id,
        "catalog_verified": True,
        "artist_name": artist,
        "track_name": title,
        "album_name": "The Click (Deluxe Edition)",
        "external_url": url or (
            "https://music.apple.com/us/album/bang/1713833569?"
            f"i={provider_id}&uo=4"
        ),
    }


class LookupSource:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    async def lookup_itunes_track(self, provider_id):
        self.calls.append(provider_id)
        return dict(self.row) if self.row else {}


def test_apple_music_share_catalog_requires_no_second_credential():
    catalog = AppleMusicShareCatalog(_sonos(), lookup_source=LookupSource())

    status = catalog.status()

    assert status["credentials_required"] is False
    assert status["playback_adapter"] == "sonos_apple_music_share_link"
    assert status["playback_verified"] is False
    assert status["verification_state"] == "queue_test_required"
    assert status["actuation_allowed"] is False


@pytest.mark.asyncio
async def test_exact_apple_share_identity_stays_pending_before_household_proof():
    catalog = AppleMusicShareCatalog(_sonos(), lookup_source=LookupSource())
    good = _track()

    resolved = await catalog.resolve_tracks("AJR", [good])

    candidate = resolved[("itunes_search", "1713833576")]
    assert candidate.provider == "itunes_search"
    assert candidate.provider_id == "1713833576"
    assert candidate.catalog_verified is True
    assert candidate.playback_capable is False
    assert candidate.playback_capability == "pending_verification"
    assert candidate.playback_adapter is None
    assert candidate.playback_reference is None
    assert candidate.metadata["apple_music_canonical"] == "song:1713833576"
    assert candidate.metadata["playback_verification"] == "queue_test_required"


@pytest.mark.asyncio
async def test_verified_household_upgrades_only_exact_apple_share_identity():
    catalog = AppleMusicShareCatalog(
        _sonos(),
        lookup_source=LookupSource(),
        verified_household_id="HH-TEST",
    )
    good = _track()
    wrong_id_url = _track(
        "999",
        title="Wrong ID",
        url="https://music.apple.com/us/album/bang/1713833569?i=1713833576&uo=4",
    )
    wrong_artist = _track("1713833577", artist="Other Artist", title="Other")

    resolved = await catalog.resolve_tracks("AJR", [good, wrong_id_url, wrong_artist])

    assert list(resolved) == [("itunes_search", "1713833576")]
    candidate = resolved[("itunes_search", "1713833576")]
    assert candidate.playback_capable is True
    assert candidate.playback_adapter == "sonos_apple_music_share_link"
    assert candidate.playback_reference == good["external_url"]
    assert candidate.metadata["playback_verification"] == "live_verified"
    status = catalog.status()
    assert status["playback_verified"] is True
    assert status["verification_state"] == "live_verified"


def test_household_mismatch_does_not_reuse_old_live_proof():
    catalog = AppleMusicShareCatalog(
        _sonos(household_id="HH-OTHER"),
        lookup_source=LookupSource(),
        verified_household_id="HH-TEST",
    )

    assert catalog.playback_verified is False
    assert catalog.status()["verification_state"] == "queue_test_required"


@pytest.mark.asyncio
async def test_get_by_identity_reverifies_exact_itunes_identity():
    row = _track()
    source = LookupSource(row)
    catalog = AppleMusicShareCatalog(_sonos(), lookup_source=source)

    candidate = await catalog.get_by_identity("itunes_search", "1713833576")
    wrong_provider = await catalog.get_by_identity("sonos_favorite", "1713833576")

    assert candidate is not None
    assert candidate.provider_id == "1713833576"
    assert source.calls == ["1713833576"]
    assert wrong_provider is None


@pytest.mark.asyncio
async def test_apple_share_catalog_fails_closed_when_sonos_is_unavailable():
    source = LookupSource(_track())
    catalog = AppleMusicShareCatalog(_sonos(connected=False), lookup_source=source)

    resolved = await catalog.resolve_tracks("AJR", [_track()])
    exact = await catalog.get_by_identity("itunes_search", "1713833576")

    assert resolved == {}
    assert exact is None
    assert source.calls == []


@pytest.mark.asyncio
async def test_composite_does_not_promote_unverified_sharelink_candidate():
    apple = AppleMusicShareCatalog(_sonos(), lookup_source=LookupSource())
    composite = CompositeMusicCatalog(apple)

    resolved = await composite.resolve_tracks("AJR", [_track()])

    assert resolved == {}


@pytest.mark.asyncio
async def test_composite_catalog_exact_lookup_does_not_require_broad_search():
    candidate = VerifiedMusicCandidate(
        provider="exact", provider_id="1", media_type="track",
        title="Track", uri="https://example/1", source="test",
        catalog_verified=True, playback_capability="supported",
        playback_adapter="test", playback_reference="1",
    )

    class ExactCatalog:
        available = True

        def __init__(self):
            self.lookup_calls = []
            self.search_calls = 0

        async def search(self, intent, *, limit=12):
            self.search_calls += 1
            return []

        async def get_by_identity(self, provider, provider_id):
            self.lookup_calls.append((provider, provider_id))
            return candidate if (provider, provider_id) == ("exact", "1") else None

        async def resolve_tracks(self, artist_name, tracks):
            return {}

    exact = ExactCatalog()
    composite = CompositeMusicCatalog(exact)

    result = await composite.get_by_identity("exact", "1")

    assert result == candidate
    assert exact.lookup_calls == [("exact", "1")]
    assert exact.search_calls == 0


@pytest.mark.asyncio
async def test_favorites_catalog_exact_identity_lookup_preserves_existing_adapter():
    class Sonos:
        connected = True

        async def get_favorites(self):
            return [{
                "id": "fav-1",
                "title": "Known Playlist",
                "uri": "sonos://playlist",
                "source": "playlist",
                "playback_supported": True,
            }]

    catalog = SonosFavoritesCatalog(Sonos())
    candidate = await catalog.get_by_identity("sonos_favorite", "fav-1")

    assert candidate is not None
    assert candidate.title == "Known Playlist"
    assert candidate.playback_adapter == "sonos_favorite_title"
