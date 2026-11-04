"""Offline ACK inspection only. No IO, logging, clients, or retained input.

Inputs must be exclusively owned, stable built-in JSON trees during the call.
Mutable containers are copied after bounded validation; subclasses are rejected.
Already-decoded dictionaries cannot reveal duplicate JSON keys: use decode_json
on original in-memory text when provenance does not guarantee unique keys.
"""
import json

PROPERTIES = ("on", "bri", "hue", "sat", "ct", "transitiontime")
RANGES = {"bri": (0, 254), "hue": (0, 65535), "sat": (0, 254),
          "ct": (153, 500), "transitiontime": (0, 65535)}


def _copy(value, budget, depth=0):
    budget[0] -= 1
    if budget[0] < 0 or depth > 8:
        raise ValueError
    kind = type(value)
    if kind is str:
        if len(value) > 512:
            raise ValueError
        return value
    if value is None or kind is bool:
        return value
    if kind is int and value.bit_length() <= 64:
        return value
    if kind is list:
        if len(value) > 32:
            raise ValueError
        return [_copy(v, budget, depth + 1) for v in value]
    if kind is dict:
        if len(value) > 16:
            raise ValueError
        result = {}
        for k, v in value.items():
            if type(k) is not str or len(k) > 512:
                raise ValueError
            result[k] = _copy(v, budget, depth + 1)
        return result
    raise ValueError


def decode_json(text):
    """Return a bounded JSON tree or None; reject duplicate keys at every level.

    No file interface. None is an invalid inspection input. Never echo errors.
    """
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    try:
        if type(text) is not str or len(text) > 16384:
            return None
        return _copy(json.loads(text, object_pairs_hook=pairs), [256])
    except Exception:
        return None


def _base(protocol):
    return {"schema_version": 1, "protocol": protocol,
            "http_result": "UNAVAILABLE" if protocol == "V1" else "FAILURE",
            "shape": "MALFORMED",
            "acceptance": "INCOMPLETE_OR_UNKNOWN", "remote_outcome": "UNKNOWN",
            "ack_count": 0, "error_count": 0, "data_count": 0,
            "requested_properties": [], "acknowledged_properties": [],
            "resource_matches": False, "values_match": False,
            "normalization_detected": False}


def _valid_property(key, value):
    if key == "on":
        return type(value) is bool
    return (key in RANGES and type(value) is int
            and RANGES[key][0] <= value <= RANGES[key][1])


def summarize_v1(response, expected_command, light_id):
    """Require phue2 nested [[per-property ACKs]], exact types/values/paths.

    No normalization is accepted. False normalization_detected means no
    supported normalization inference, not proof that firmware never normalizes.
    """
    out = _base("V1")
    try:
        response, command, ident = _copy(
            [response, expected_command, light_id], [256])
        if (type(ident) is not str or not ident or "/" in ident
                or type(command) is not dict or not 1 <= len(command) <= 6
                or any(not _valid_property(k, v) for k, v in command.items())
                or ("ct" in command and ("hue" in command
                    or ("sat" in command and command["sat"] != 0)))):
            return out
        out["requested_properties"] = [k for k in PROPERTIES if k in command]
        if (type(response) is not list or len(response) != 1
                or type(response[0]) is not list or not response[0]):
            return out
        expected = {"/lights/" + ident + "/state/" + k: k for k in command}
        seen = set()
        matching = True
        for entry in response[0]:
            if type(entry) is not dict:
                return out
            if set(entry) == {"error"} and type(entry["error"]) is dict:
                out["error_count"] += 1
                continue
            if set(entry) != {"success"}:
                return out
            ack = entry["success"]
            if type(ack) is not dict or len(ack) != 1:
                return out
            path, value = next(iter(ack.items()))
            if path not in expected or path in seen:
                return out
            seen.add(path)
            key = expected[path]
            matching = matching and _valid_property(key, value) and value == command[key]
        out["ack_count"] = len(seen)
        out["acknowledged_properties"] = [k for k in PROPERTIES
                                             if any(expected[p] == k for p in seen)]
        out["resource_matches"] = bool(seen)
        out["values_match"] = bool(seen) and matching
        complete = seen == set(expected) and matching and not out["error_count"]
        out["shape"] = "COMPLETE" if complete else "PARTIAL"
        if complete:
            out["acceptance"] = "ACCEPTED_NOT_PHYSICAL"
        return out
    except Exception:
        return _base("V1")


def summarize_v2(status, response, expected_id, expected_type):
    """Strict single matching resource policy; 200/207 alone prove nothing."""
    out = _base("V2")
    try:
        status, response, ident, kind = _copy(
            [status, response, expected_id, expected_type], [256])
        if type(status) is not int or not 100 <= status <= 599:
            return out
        out["http_result"] = str(status) if status in (200, 207) else "FAILURE"
        if (type(ident) is not str or not ident or kind not in ("light", "scene")
                or type(response) is not dict or set(response) != {"errors", "data"}
                or type(response["errors"]) is not list
                or type(response["data"]) is not list):
            return out
        errors, data = response["errors"], response["data"]
        if any(type(e) is not dict or not e for e in errors):
            return out
        out["error_count"], out["data_count"] = len(errors), len(data)
        for entry in data:
            if (type(entry) is not dict or set(entry) != {"rid", "rtype"}
                    or type(entry["rid"]) is not str or not entry["rid"]
                    or type(entry["rtype"]) is not str):
                return out
        out["ack_count"] = len(data)
        out["resource_matches"] = (len(data) == 1 and data[0]["rid"] == ident
                                    and data[0]["rtype"] == kind)
        complete = (status in (200, 207) and not errors and out["resource_matches"])
        out["shape"] = "COMPLETE" if complete else "PARTIAL"
        if complete:
            out["acceptance"] = "ACCEPTED_NOT_PHYSICAL"
        return out
    except Exception:
        return _base("V2")
