"""OFFLINE-only raw-body candidate; not an authenticated endpoint; no transport.

Fictional fixtures only. No Origin, Host, forwarded headers or caller-supplied
transport_verified claim can prove identity or transport here. Parsing grants
no consent, retention, eligibility, or live transfer authority.
"""
from __future__ import annotations

import json
from unicodedata import category

from backend.services.apple_music_ephemeral_review_receiver import (
    EphemeralReview, ReviewRefused, _validate_body,
)

MAX_RAW_BODY_BYTES = 2048  # Proposed offline limit, including whitespace/BOM.


def _refuse_number(token: str) -> None:
    # No numeric field exists. Never convert even huge integers/exponents.
    raise ReviewRefused()


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result or any(category(ch).startswith("C") for ch in key):
            raise ReviewRefused()
        if isinstance(value, str) and any(category(ch).startswith("C") for ch in value):
            raise ReviewRefused()
        result[key] = value
    return result


def parse_offline_artist_raw_body(raw: bytes) -> EphemeralReview:
    """Validate exact eight-field bytes; not an authenticated endpoint; no transport.

    Returns an immutable, repr-redacted review with existing unverified semantics.
    No state is retained. Refusals have one fixed message, without decoder chains.
    This does not bound streamed accumulation or erase caller/decoder byte copies.
    """
    if type(raw) is not bytes or not raw or len(raw) > MAX_RAW_BODY_BYTES:
        raise ReviewRefused()
    try:
        if raw.startswith(b"\xef\xbb\xbf"):
            raise ReviewRefused()
        body = json.loads(raw.decode("utf-8", errors="strict"),
                          object_pairs_hook=_object, parse_int=_refuse_number,
                          parse_float=_refuse_number, parse_constant=_refuse_number)
        return EphemeralReview(_validate_body(body))
    except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
        pass
    # Raise outside the handler so raw-bearing JSONDecodeError is not retained
    # as exception context (even a suppressed context could expose its .doc).
    raise ReviewRefused()
