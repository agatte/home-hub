"""Read-only listening cards from server-produced MusicRequestResult evidence.

This projection grants no playback authority. An album link establishes a
catalog destination, not the album's full contents or session playability.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


def _album_link(track: dict[str, Any]) -> tuple[str, str] | None:
    if track.get("provider") != "itunes_search" or track.get("catalog_verified") is not True:
        return None
    album_id = str(track.get("album_provider_id") or "")
    url = track.get("album_external_url")
    if not re.fullmatch(r"[0-9]+", album_id) or not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc not in {"music.apple.com", "itunes.apple.com"}:
            return None
        if not re.fullmatch(r"/[a-z]{2}/album/(?:[^/]+/)?(?:id)?" + album_id, parsed.path):
            return None
        # The provider returned the collection URL, not a track destination.
        # Remove query/fragment so no song or tracking parameter is carried over.
        return album_id, urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
    except ValueError:
        return None


def build_listening_choices(payload: dict[str, Any], *, limit: int = 6) -> dict[str, Any]:
    """Present coherent choices without inventing provider identities or media."""
    if not 1 <= limit <= 10:
        raise ValueError("limit must be between 1 and 10")
    familiar = []
    discovery = []
    seen = set()
    for item in payload.get("familiar_suggestions") or ():
        candidate = item.get("candidate") or {}
        trust = item.get("trust") or {}
        if (
            candidate.get("provider") != "sonos_favorite"
            or candidate.get("media_type") != "favorite"
            or candidate.get("verified") is not True
            or candidate.get("catalog_verified") is not True
            or candidate.get("playback_capable") is not True
            or item.get("taste_classification") not in {"familiar", "proven"}
            or "explicit approval was revoked" in trust.get("reasons", ())
            or not candidate.get("provider_id")
            or not candidate.get("title")
        ):
            continue
        key = ("sonos_favorite", candidate["provider_id"])
        if key in seen:
            continue
        seen.add(key)
        familiar.append({
            "id": ":".join(key),
            "kind": "favorite",
            "title": candidate["title"],
            "familiarity": item["taste_classification"],
            "reasons": item.get("reasons", []),
            "sonos": "existing_favorite",
            "apple_music_url": None,
        })

    artists = set()
    mood_tracks = []
    mood_ids = set()
    mood_artists = set()
    for cluster in (payload.get("discovery") or {}).get("clusters") or ():
        artist = str(cluster.get("artist_name") or "").strip()
        artist_key = artist.casefold()
        if not artist or artist_key in artists or cluster.get("artist_classification") == "rejected":
            continue
        tracks = []
        track_keys = set()
        for track in cluster.get("tracks") or ():
            provider = track.get("provider")
            identity = track.get("provider_id")
            if (
                provider != "itunes_search"
                or not isinstance(identity, str)
                or not identity.isascii()
                or not identity.isdigit()
                or track.get("catalog_verified") is not True
                or track.get("taste_classification") == "rejected"
                or not track.get("track_name")
                or str(track.get("artist_name") or "").casefold() != artist_key
                or identity in track_keys
            ):
                continue
            track_keys.add(identity)
            tracks.append(track)
        if not tracks:
            continue
        # Each cluster already contains individually mood/taste-qualified tracks.
        # Only exact supported ShareLink evidence may become an actionable mix.
        from backend.services.sonos_service import SonosService
        playable = []
        for track in tracks:
            try:
                exact = SonosService._canonical_apple_music_share_link(track.get("playback_reference") or "")
            except Exception:
                exact = None
            if (track.get("playback_capability") == "supported"
                    and track.get("playback_adapter") == "sonos_apple_music_share_link"
                    and track.get("playback_reason") == "provider_exact_match"
                    and exact == "song:" + track["provider_id"]):
                playable.append(track)
        if playable and artist_key not in mood_artists and playable[0]["provider_id"] not in mood_ids:
            mood_artists.add(artist_key)
            mood_ids.add(playable[0]["provider_id"])
            mood_tracks.append(playable[0])
        album = None
        for track in tracks:
            link = _album_link(track)
            if link and track.get("album_name") and ("itunes_album", link[0]) not in seen:
                album = (track, *link)
                break
        base = {
            "artist": artist,
            "familiarity": cluster.get("artist_classification") or "unknown",
            "reasons": cluster.get("reasons", []),
        }
        # Offer a mix as well as albums across different artists. A sampler
        # represents exact track identities, not a provider-created playlist.
        if len(playable) >= 2:
            playable = playable[:5]
            identities = [track["provider_id"] for track in playable]
            choice = {
                **base,
                "id": "artist_mix:" + ",".join(identities),
                "kind": "artist_mix",
                "title": artist + " mix",
                "tracks": [
                    {"provider": "itunes_search", "provider_id": track["provider_id"],
                     "title": track["track_name"], "artist": artist}
                    for track in playable
                ],
                "sonos": "session_required",
                "apple_music_url": None,
            }
            discovery.append(choice)
        if album is not None:
            track, album_id, link = album
            seen.add(("itunes_album", album_id))
            choice = {
                **base,
                "id": "itunes_album:" + album_id,
                "kind": "album",
                "title": track["album_name"],
                "matched_track": track["track_name"],
                "sonos": "not_verified",
                "apple_music_url": link,
            }
            discovery.append(choice)
        if len(playable) >= 2 or album is not None:
            artists.add(artist_key)

    # artist_mix is the existing exact ordered track contract, also used for
    # cross-artist mixes. Per-track artists are mandatory for revalidation.
    if len(mood_tracks) >= 2:
        mood_tracks = mood_tracks[:5]
        discovery.insert(0, {
            "id": "artist_mix:" + ",".join(t["provider_id"] for t in mood_tracks),
            "kind": "artist_mix", "title": "Mood mix", "artist": None,
            "tracks": [{"provider": "itunes_search", "provider_id": t["provider_id"],
                        "title": t["track_name"], "artist": t["artist_name"]}
                       for t in mood_tracks],
            "sonos": "session_required", "apple_music_url": None,
        })

    choices = []
    for index in range(max(len(familiar), len(discovery))):
        if index < len(familiar):
            choices.append(familiar[index])
        if index < len(discovery):
            choices.append(discovery[index])
        if len(choices) >= limit:
            break
    choices = choices[:limit]
    # Preserve a catalog album destination when the bounded list has room
    # for it alongside at least one playable choice.
    albums = [row for row in discovery if row["kind"] == "album"]
    if limit >= 2 and albums and not any(row["kind"] == "album" for row in choices):
        choices[-1] = albums[0]
    return {
        "status": "ready" if len(choices) == limit else "partial" if choices else "unavailable",
        "choices": choices,
        "actuation_allowed": False,
        "continuation_available": False,
        "session_playback_available": False,
    }
