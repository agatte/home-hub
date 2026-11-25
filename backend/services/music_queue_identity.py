"""Narrow Apple queue resource identity for explicit listening.

Only the tested native song resource and Apple service identifier are
supported. A numeric ID alone is not provider identity. Other native formats
require physical evidence before adding support.
"""
import re
from urllib.parse import parse_qs, unquote, urlsplit


def apple_song_id(uri: str) -> str | None:
    if not isinstance(uri, str) or not uri:
        return None
    try:
        parsed = urlsplit(uri)
        if parsed.fragment or parse_qs(parsed.query, keep_blank_values=True).get("sid") != ["204"]:
            return None
        match = re.fullmatch(r"x-sonos-http:song:([0-9]+)", unquote(uri.split("?", 1)[0]),
                             flags=re.IGNORECASE)
        return match.group(1) if match else None
    except ValueError:
        return None


def play_source_fingerprint(evidence):
    """Exact source and track identity, including metadata. Unknown is not empty."""
    if not isinstance(evidence, dict):
        return None
    proof = tuple(evidence.get(key) for key in (
        "current_uri", "queue_track_uri", "media_metadata", "metadata",
    ))
    return proof if all(isinstance(value, str) for value in proof) else None


def selected_apple_source(proof, uid, provider_id):
    """Only unloaded or the exact selected Apple track on its own queue/source."""
    if not proof or len(proof) != 4:
        return False
    uri, track, media_metadata, metadata = proof
    if not track:
        return not any((uri, media_metadata, metadata))
    return (
        apple_song_id(track) == provider_id
        and uri in {track, f"x-rincon-queue:{uid}#0"}
    )
