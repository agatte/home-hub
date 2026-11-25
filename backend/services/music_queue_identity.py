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
