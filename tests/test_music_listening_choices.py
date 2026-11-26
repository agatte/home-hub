from backend.services.music_listening_choices import build_listening_choices


def _track(identity="12", *, album_id="100", artist="Example Artist"):
    return {
        "provider": "itunes_search",
        "provider_id": identity,
        "catalog_verified": True,
        "playback_capability": "supported",
        "playback_adapter": "sonos_apple_music_share_link",
        "playback_reference": f"https://music.apple.com/us/album/example/1?i={identity}",
        "playback_reason": "provider_exact_match",
        "artist_name": artist,
        "track_name": "Example Track " + identity,
        "album_name": "Example Album",
        "album_provider_id": album_id,
        "album_external_url": f"https://music.apple.com/us/album/example/{album_id}?uo=4",
        "taste_classification": "exploratory",
    }


def _cluster(*tracks, artist="Example Artist"):
    return {"artist_name": artist, "artist_classification": "exploratory",
            "tracks": list(tracks), "reasons": ["related artist"]}


def _favorite(identity="fav1"):
    return {
        "candidate": {
            "provider": "sonos_favorite", "provider_id": identity,
            "media_type": "favorite", "title": "Familiar playlist",
            "verified": True, "catalog_verified": True, "playback_capable": True,
        },
        "taste_classification": "proven",
        "reasons": ["familiar"],
    }


def _build(*clusters, favorites=(), limit=6):
    return build_listening_choices({
        "familiar_suggestions": list(favorites),
        "discovery": {"clusters": list(clusters)},
    }, limit=limit)


def test_interleaves_verified_favorites_albums_and_exact_artist_mixes():
    result = _build(
        _cluster(_track()),
        _cluster(_track("21", album_id="200", artist="Other"),
                 _track("22", album_id="200", artist="Other"), artist="Other"),
        favorites=[_favorite()], limit=3,
    )
    assert result["status"] == "ready"
    assert [choice["kind"] for choice in result["choices"]] == ["favorite", "artist_mix", "album"]
    mix = result["choices"][1]
    assert mix["id"] == "artist_mix:12,21"
    assert [track["artist"] for track in mix["tracks"]] == ["Example Artist", "Other"]
    album = result["choices"][2]
    assert album["id"] == "itunes_album:100"
    assert album["apple_music_url"] == "https://music.apple.com/us/album/example/100"
    assert album["sonos"] == "not_verified"
    assert result["actuation_allowed"] is False
    assert result["session_playback_available"] is False
    assert result["continuation_available"] is False


def test_does_not_invent_album_link_from_title_or_accept_mismatched_provider_id():
    for change in (
        {"album_provider_id": None},
        {"album_external_url": "https://music.apple.com/us/album/example/999"},
        {"album_external_url": "https://music.apple.com.evil.example/us/album/example/100"},
        {"album_external_url": "https://music.apple.com@evil.example/us/album/example/100"},
        {"album_external_url": "https://music.apple.com/us/song/example/100"},
        {"album_external_url": "http://music.apple.com/us/album/example/100"},
        {"catalog_verified": False},
        {"taste_classification": "rejected"},
    ):
        result = _build(_cluster({**_track(), **change}))
        assert result["status"] == "unavailable"
        assert result["choices"] == []


def test_partial_results_without_history_and_duplicate_artists_or_tracks():
    first = _track(album_id="")
    result = _build(_cluster(first, first, _track("13", album_id="")),
                    _cluster(_track("14")))
    assert result["status"] == "partial"
    assert len(result["choices"]) == 1
    assert result["choices"][0]["kind"] == "artist_mix"
    assert len(result["choices"][0]["tracks"]) == 2


def test_rejected_or_wrong_artist_tracks_and_revoked_favorites_excluded():
    revoked = {**_favorite(), "trust": {"reasons": ["explicit approval was revoked"]}}
    result = _build(_cluster({**_track(), "taste_classification": "rejected"},
                             _track("13", artist="Different")),
                    favorites=[revoked])
    assert result["status"] == "unavailable"


def test_duplicate_collection_is_not_repeated():
    result = _build(_cluster(_track()), _cluster(_track("15", artist="Other"), artist="Other"))
    assert sum(c["kind"] == "album" for c in result["choices"]) == 1

def test_metadata_only_and_rejected_tracks_do_not_form_mood_mix():
    first = _track()
    second = _track("15", artist="Other")
    for changed in ({"playback_capability": "metadata_only"},
                    {"playback_reference": "https://music.apple.com/us/album/example/1?i=99"},
                    {"taste_classification": "rejected"}):
        result = _build(_cluster(first), _cluster({**second, **changed}, artist="Other"))
        assert all(choice["kind"] != "artist_mix" for choice in result["choices"])


def test_playable_artist_keeps_album_destination():
    cluster = _cluster(_track(), _track("13"))
    result = _build(cluster, limit=2)
    assert [c["kind"] for c in result["choices"]] == ["artist_mix", "album"]
    assert result["choices"][1]["id"] == "itunes_album:100"
    assert result["choices"][1]["sonos"] == "not_verified"
    assert _build(cluster, limit=1)["choices"][0]["kind"] == "artist_mix"
    crowded = _build(cluster, favorites=[_favorite("1"), _favorite("2")], limit=2)
    assert [c["kind"] for c in crowded["choices"]] == ["favorite", "album"]
