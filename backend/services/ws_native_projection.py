"""Fixed #293 native-client projections used by the authenticated runtime.

The runtime MUST supply
profile and lane from an authenticated, nonrevoked server-bound identity.
Unknown messages, profiles and lanes deny. Never broadcast the original
unfiltered event to an authenticated native client after a projection miss.
"""
from collections.abc import Mapping
from typing import Any


def _text(value: object, limit: int) -> str | None:
    return value if type(value) is str and 0 < len(value) <= limit else None


def _notification(data: object) -> dict[str, Any] | None:
    if not isinstance(data, Mapping):
        return None
    title = _text(data.get("title"), 200)
    if title is None:
        return None
    result: dict[str, Any] = {"title": title}
    for field, bound in (("subtitle", 600), ("kind", 80), ("output_delta", 200)):
        value = data.get(field)
        if value is not None:
            if value == "" and field in ("subtitle", "output_delta"):
                continue
            checked = _text(value, bound)
            if checked is None:
                return None
            result[field] = checked

    factors = data.get("factors", [])
    if not isinstance(factors, list) or len(factors) > 6:
        return None
    safe_factors: list[dict[str, str]] = []
    for factor in factors:
        if not isinstance(factor, Mapping):
            return None
        label = _text(factor.get("label"), 200)
        value = _text(factor.get("value"), 300)
        if label is None or value is None:
            return None
        safe_factors.append({"label": label, "value": value})
    result["factors"] = safe_factors

    # The notifier executes URLs supplied in button actions; neither a
    # relative path nor HTTP(S) URL is safe to forward before server-bound
    # authorization, fixed action identifiers and redirect policy exist.
    # Preserve the text toast, but expose no executable actions in this
    # offline projection (including otherwise-valid legacy action payloads).
    result["actions"] = []
    return result


def project_native_ws_event(
    *, profile: object, lane: object, message_type: object, data: object,
) -> dict[str, Any] | None:
    """Select narrow native-client wire payload; None means do not deliver.

    This only describes two native projections. Owner/kiosk profiles require
    separate reviewed event schemas; do not treat a miss as a full-frame grant.
    """
    # Exact built-in strings only: untrusted in-process values with overloaded
    # equality must not select a grant or survive into an unsafe wire payload.
    if any(type(value) is not str for value in (profile, lane, message_type)):
        return None
    if (profile, lane, message_type) == ("windows_desktop", "display", "mode_update"):
        if not isinstance(data, Mapping):
            return None
        mode = _text(data.get("mode"), 80)
        if mode is None:
            return None
        payload: dict[str, str] = {"mode": mode}
        period = data.get("time_period")
        if period is not None:
            period = _text(period, 40)
            if period is None:
                return None
            payload["time_period"] = period
        return {"type": "mode_update", "data": payload}

    if (profile, lane, message_type) == ("desktop_notifier", "notifier", "notification"):
        payload = _notification(data)
        return {"type": "notification", "data": payload} if payload is not None else None
    return None
