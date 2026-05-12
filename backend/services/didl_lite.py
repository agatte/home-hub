"""
DIDL-Lite envelope builder for SoCo's ``device.play_uri(meta=...)``.

Sonos sources Now Playing's title/artist/album/album-art from a DIDL-Lite XML
envelope passed alongside the stream URI. Plain HTTP streams (iTunes previews,
self-hosted MP3s) have no embedded ID3, so without this envelope ``Now Playing``
goes blank.

This module emits a minimal but complete envelope for an audio track. Tested
shape, escaped strings — keep this file lean; envelope drift is exacting.
"""
from __future__ import annotations

from typing import Optional
from xml.sax.saxutils import escape

# DIDL-Lite envelope skeleton. The trailing ``cdudn`` desc element with
# ``RINCON_AssociatedZPUDN`` is what tells Sonos to render the item via the
# default associated UPnP renderer — needed for arbitrary HTTP streams to
# show title/artist on the speaker's Now Playing.
_DIDL_HEADER = (
    '<DIDL-Lite '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
    'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
    'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
)
_DIDL_FOOTER = "</DIDL-Lite>"

_UPNP_CLASS_MUSIC_TRACK = "object.item.audioItem.musicTrack"
_SONOS_RENDERER_DESC = (
    '<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
    "RINCON_AssociatedZPUDN"
    "</desc>"
)


def build_track_didl_lite(
    *,
    title: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    album_art_uri: Optional[str] = None,
    item_id: str = "-1",
    parent_id: str = "-1",
) -> str:
    """Build a DIDL-Lite envelope for an audio track.

    Args:
        title: Track title (required — empty → empty envelope returned).
        artist: Artist name (``dc:creator`` + ``upnp:artist``).
        album: Album name (``upnp:album``).
        album_art_uri: HTTP URL of cover art (``upnp:albumArtURI``).
        item_id: DIDL item id; SoCo expects ``-1`` for ad-hoc URIs.
        parent_id: DIDL parent id; SoCo expects ``-1`` for ad-hoc URIs.

    Returns:
        A complete DIDL-Lite XML string. Returns ``""`` if title is empty —
        callers should treat empty as "skip the meta param" so SoCo's
        default behavior takes over.

    All string fields are XML-escaped. Album/artist/art are optional; the
    envelope only emits elements for fields that are present and non-empty.
    """
    if not title or not title.strip():
        return ""

    parts: list[str] = [
        _DIDL_HEADER,
        f'<item id="{escape(item_id)}" parentID="{escape(parent_id)}" restricted="true">',
        f"<dc:title>{escape(title)}</dc:title>",
    ]

    if artist and artist.strip():
        # dc:creator is what Sonos's Now Playing renders as "Artist".
        # upnp:artist mirrors it for the wider UPnP ecosystem.
        parts.append(f"<dc:creator>{escape(artist)}</dc:creator>")
        parts.append(f"<upnp:artist>{escape(artist)}</upnp:artist>")

    if album and album.strip():
        parts.append(f"<upnp:album>{escape(album)}</upnp:album>")

    if album_art_uri and album_art_uri.strip():
        parts.append(f"<upnp:albumArtURI>{escape(album_art_uri)}</upnp:albumArtURI>")

    parts.append(f"<upnp:class>{_UPNP_CLASS_MUSIC_TRACK}</upnp:class>")
    parts.append(_SONOS_RENDERER_DESC)
    parts.append("</item>")
    parts.append(_DIDL_FOOTER)

    return "".join(parts)
