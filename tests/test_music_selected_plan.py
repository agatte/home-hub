from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services.music_discovery import DiscoveryArtistCluster, DiscoveryTrack, MusicDiscoveryResult
from backend.services.music_requests import (
    FamiliarMusicSuggestion, MusicRequest, MusicRequestResolver, MusicRequestResult,
)
from backend.services.music_selected_plan import SelectedListeningPlanner
from backend.services.playlist_catalog import VerifiedMusicCandidate


def song(identity):
    url = f"https://music.apple.com/us/song/example/{identity}"
    return VerifiedMusicCandidate(
        "itunes_search", identity, "track", f"Track {identity}", url, "itunes_search+sonos_share_link",
        playback_capability="supported", playback_adapter="sonos_apple_music_share_link",
        playback_reference=url, metadata={
            "artist_name": "Artist", "apple_music_canonical": f"song:{identity}",
            "playback_verification": "live_verified",
        },
    )


def favorite():
    return VerifiedMusicCandidate(
        "sonos_favorite", "fav1", "favorite", "Known", "uri:one", "playlist",
        playback_capability="supported", playback_adapter="sonos_favorite_title",
        playback_reference="Known",
    )


def track(identity, album=False):
    return DiscoveryTrack(
        "itunes_search", identity, True, "supported", "sonos_apple_music_share_link",
        f"https://music.apple.com/us/album/example/1?i={identity}", "provider_exact_match",
        "Artist", f"Track {identity}", "Album" if album else None, None, None, None,
        "exploratory", 0, (), "123" if album else None,
        "https://music.apple.com/us/album/example/123" if album else None,
    )


def request(*, album=False, duplicate=False):
    cluster = DiscoveryArtistCluster(
        "Artist", "Seed", "synthetic", 1, 1, "exploratory", 0, 0, 1,
        None, None, None, (), (), (track("11", album), track("12", album)), (),
    )
    discovery = MusicDiscoveryResult(
        "shadow_ready", "general", "gentle", datetime.now(timezone.utc),
        (cluster,), "synthetic", True,
    )
    resolved = MusicRequestResolver().resolve(MusicRequest("relaxing", listening=True))
    suggestion = FamiliarMusicSuggestion(favorite(), 1, "familiar", 1, ())
    return MusicRequestResult(
        "shadow_ready", resolved, (suggestion, suggestion) if duplicate else (suggestion,), discovery,
    )


class Catalog:
    def __init__(self, items):
        self.items = items
        self.calls = []

    async def get_by_identity(self, provider, identity):
        self.calls.append((provider, identity))
        return self.items.get(identity)


class Taste:
    def __init__(self, classes=None, fail=False):
        self.classes = classes or {}
        self.fail = fail

    async def snapshot(self):
        if self.fail:
            raise RuntimeError("unavailable")
        return self

    def classify_candidate(self, item, *, mode):
        value = self.classes.get(item.provider_id, ("familiar", 1))
        return SimpleNamespace(classification=value[0], preference=value[1])


class Approvals:
    def __init__(self, actions=None, fail=False):
        self.actions = actions or {}
        self.fail = fail

    async def latest_actions(self, candidates):
        if self.fail:
            raise RuntimeError("unavailable")
        return self.actions


def planner(items, taste=None, approvals=None):
    catalog = Catalog(items)
    return SelectedListeningPlanner(
        catalog=catalog, taste_provider=taste or Taste(), approval_service=approvals or Approvals(),
    ), catalog


@pytest.mark.asyncio
async def test_mix_reverifies_only_displayed_members_in_order_without_track_approval():
    p, catalog = planner({"11": song("11"), "12": song("12"), "fav1": favorite()},
                         Taste({"11": ("exploratory", 0)}))
    result = await p.preview(request(), "artist_mix:11,12")
    assert result.status == "verified_preview"
    assert result.reason == "execution_not_connected"
    assert result.actuation_allowed is False
    assert [c.provider_id for c in result.candidates] == ["11", "12"]
    assert catalog.calls == [("itunes_search", "11"), ("itunes_search", "12")]


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", [
    None, song("99"), replace(song("12"), title="Different"),
    replace(song("12"), playback_capability="pending_verification"),
    replace(song("12"), metadata={"artist_name": "Different"}),
])
async def test_mix_fails_whole_selection_instead_of_substituting(wrong):
    p, _ = planner({"11": song("11"), "12": wrong, "99": song("99")})
    result = await p.preview(request(), "artist_mix:11,12")
    assert result.reason == "mix_member_not_verified"
    assert result.candidates == ()
    assert result.actuation_allowed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("taste,approvals,reason", [
    (Taste({"12": ("rejected", 1)}), Approvals(), "current_taste_or_approval_veto"),
    (Taste({"12": ("exploratory", float("nan"))}), Approvals(), "current_taste_or_approval_veto"),
    (Taste(), Approvals({("itunes_search", "12"): "revoke"}), "current_taste_or_approval_veto"),
    (Taste(fail=True), Approvals(), "taste_or_approval_unavailable"),
    (Taste(), Approvals(fail=True), "taste_or_approval_unavailable"),
])
async def test_current_vetoes_and_missing_evidence(taste, approvals, reason):
    p, _ = planner({"11": song("11"), "12": song("12")}, taste, approvals)
    result = await p.preview(request(), "artist_mix:11,12")
    assert result.reason == reason
    assert not result.candidates


@pytest.mark.asyncio
async def test_exact_favorite_reverified_without_claiming_title_execution():
    p, catalog = planner({"fav1": favorite()})
    result = await p.preview(request(), "sonos_favorite:fav1")
    assert result.status == "verified_preview"
    assert result.reason == "execution_not_connected"
    assert not result.actuation_allowed
    assert catalog.calls == [("sonos_favorite", "fav1")]
    p, _ = planner({"fav1": replace(favorite(), uri="uri:different")})
    assert (await p.preview(request(), "sonos_favorite:fav1")).reason == "favorite_identity_changed"


@pytest.mark.asyncio
async def test_no_hidden_forged_album_or_ambiguous_choices():
    p, catalog = planner({})
    for identity in ("artist_mix:11,99", "artist_mix:12,11", "artist_mix:11,12"):
        result = await p.preview(request(), identity, limit=1)
        assert result.reason == "choice_not_unique_or_visible"
    assert (await p.preview(request(album=True), "itunes_album:123")).reason == "album_contents_not_verified"
    assert (await p.preview(request(duplicate=True), "sonos_favorite:fav1")).reason == "ambiguous_favorite"
    assert (await p.preview(replace(request(), actuation_allowed=True), "sonos_favorite:fav1")).reason == "invalid_preview"
    with pytest.raises(TypeError):
        await p.preview({}, "sonos_favorite:fav1")
    assert catalog.calls == []
