"""
Tests for backend.services.didl_lite.build_track_didl_lite.

DIDL-Lite envelope shape is exacting — Sonos's Now Playing renderer silently
drops malformed envelopes. These tests pin:
  - the namespace declarations
  - element ordering (Sonos can be order-sensitive on some firmware)
  - XML escaping of special characters in titles/artists
  - optional-field fallbacks
  - empty-title short-circuit
"""
from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from backend.services.didl_lite import build_track_didl_lite


# ---------------------------------------------------------------------------
# Happy path — full envelope
# ---------------------------------------------------------------------------

def test_full_envelope_parses_as_xml() -> None:
    """Envelope must be valid XML — Sonos parses it strictly."""
    meta = build_track_didl_lite(
        title="Lo-Fi Beats",
        artist="ChillHop",
        album="Study Session Vol 4",
        album_art_uri="https://example.com/art.jpg",
    )
    # ET will raise on invalid XML.
    root = ET.fromstring(meta)
    assert root.tag.endswith("DIDL-Lite")


def test_full_envelope_emits_all_fields() -> None:
    meta = build_track_didl_lite(
        title="Lo-Fi Beats",
        artist="ChillHop",
        album="Study Session Vol 4",
        album_art_uri="https://example.com/art.jpg",
    )
    assert "<dc:title>Lo-Fi Beats</dc:title>" in meta
    assert "<dc:creator>ChillHop</dc:creator>" in meta
    assert "<upnp:artist>ChillHop</upnp:artist>" in meta
    assert "<upnp:album>Study Session Vol 4</upnp:album>" in meta
    assert "<upnp:albumArtURI>https://example.com/art.jpg</upnp:albumArtURI>" in meta
    assert "object.item.audioItem.musicTrack" in meta


def test_envelope_declares_required_namespaces() -> None:
    """Sonos firmware looks up dc:, upnp:, r: by namespace."""
    meta = build_track_didl_lite(title="x", artist="y")
    assert 'xmlns:dc="http://purl.org/dc/elements/1.1/"' in meta
    assert 'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"' in meta
    assert 'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/"' in meta


def test_envelope_includes_associated_renderer_desc() -> None:
    """The cdudn desc element associates the item with the default UPnP
    renderer — required for arbitrary HTTP streams to populate Now Playing."""
    meta = build_track_didl_lite(title="x")
    assert 'id="cdudn"' in meta
    assert "RINCON_AssociatedZPUDN" in meta


# ---------------------------------------------------------------------------
# Optional-field fallbacks
# ---------------------------------------------------------------------------

def test_title_only_envelope() -> None:
    """Only title required; envelope still valid + complete with no optional fields."""
    meta = build_track_didl_lite(title="Just A Title")
    root = ET.fromstring(meta)
    assert root.tag.endswith("DIDL-Lite")
    assert "<dc:title>Just A Title</dc:title>" in meta
    assert "dc:creator" not in meta
    assert "upnp:artist" not in meta
    assert "upnp:album" not in meta
    assert "upnp:albumArtURI" not in meta


def test_empty_artist_omitted() -> None:
    meta = build_track_didl_lite(title="t", artist="")
    assert "dc:creator" not in meta


def test_whitespace_only_album_omitted() -> None:
    meta = build_track_didl_lite(title="t", album="   ")
    assert "upnp:album" not in meta


def test_none_artwork_omitted() -> None:
    meta = build_track_didl_lite(title="t", album_art_uri=None)
    assert "albumArtURI" not in meta


# ---------------------------------------------------------------------------
# Empty-title short-circuit
# ---------------------------------------------------------------------------

def test_empty_title_returns_empty_string() -> None:
    """Empty/whitespace title → empty return → caller skips meta param."""
    assert build_track_didl_lite(title="") == ""
    assert build_track_didl_lite(title="   ") == ""


# ---------------------------------------------------------------------------
# XML escaping
# ---------------------------------------------------------------------------

def test_ampersand_escaped_in_title() -> None:
    meta = build_track_didl_lite(title="Rock & Roll")
    assert "Rock &amp; Roll" in meta
    assert "Rock & Roll" not in meta  # raw ampersand never appears
    ET.fromstring(meta)  # must still parse


def test_quote_escaped_in_artist() -> None:
    meta = build_track_didl_lite(title="t", artist='Foo "Bar" Baz')
    # ET.fromstring is the real authority — if it parses, escaping is fine.
    ET.fromstring(meta)


def test_lt_gt_escaped_in_album() -> None:
    meta = build_track_didl_lite(title="t", album="<Greatest> Hits")
    assert "&lt;Greatest&gt; Hits" in meta
    ET.fromstring(meta)


def test_unicode_passes_through() -> None:
    """Unicode is XML-safe natively; just confirm it round-trips."""
    meta = build_track_didl_lite(title="Beyoncé", artist="Café Tacvba")
    assert "Beyoncé" in meta
    assert "Café Tacvba" in meta
    ET.fromstring(meta)


# ---------------------------------------------------------------------------
# Item-id / parent-id customization
# ---------------------------------------------------------------------------

def test_default_item_and_parent_ids_are_minus_one() -> None:
    meta = build_track_didl_lite(title="t")
    assert 'id="-1"' in meta
    assert 'parentID="-1"' in meta


def test_custom_item_id() -> None:
    meta = build_track_didl_lite(title="t", item_id="rec:42")
    assert 'id="rec:42"' in meta


# ---------------------------------------------------------------------------
# Element ordering — Sonos firmware can drop misordered envelopes
# ---------------------------------------------------------------------------

def test_title_before_creator_before_album() -> None:
    meta = build_track_didl_lite(
        title="t",
        artist="a",
        album="al",
        album_art_uri="https://x.test/a.jpg",
    )
    # Find the indices of each tag.
    i_title = meta.index("<dc:title>")
    i_creator = meta.index("<dc:creator>")
    i_album = meta.index("<upnp:album>")
    i_class = meta.index("<upnp:class>")
    assert i_title < i_creator < i_album < i_class


def test_class_and_desc_at_end() -> None:
    meta = build_track_didl_lite(title="t")
    i_class = meta.index("<upnp:class>")
    i_desc = meta.index('<desc id="cdudn"')
    i_close_item = meta.index("</item>")
    assert i_class < i_desc < i_close_item


# ---------------------------------------------------------------------------
# Defensive — multi-element regex parse smoke check
# ---------------------------------------------------------------------------

def test_envelope_has_exactly_one_item_and_didl_root() -> None:
    meta = build_track_didl_lite(title="t", artist="a")
    assert len(re.findall(r"<item ", meta)) == 1
    assert len(re.findall(r"</item>", meta)) == 1
    assert meta.startswith("<DIDL-Lite ")
    assert meta.endswith("</DIDL-Lite>")
