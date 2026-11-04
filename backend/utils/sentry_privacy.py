"""Pure outbound Sentry error-event containment; no config or payload rendering."""


def redact_http_client_breadcrumbs(event, hint):
    """Remove HTTP-client crumbs without inspecting their data/message fields.

    Malformed breadcrumb containers are discarded; malformed events are dropped.
    Shallow copies preserve error information without modifying the input event.
    This is not a general URL scrubber for arbitrary application error content.
    """
    if type(event) is not dict:
        return None
    result = event.copy()
    if "breadcrumbs" not in result:
        return result
    crumbs = result.pop("breadcrumbs")
    if type(crumbs) is not dict or type(crumbs.get("values")) is not list:
        return result
    kept = []
    for crumb in crumbs["values"]:
        if type(crumb) is not dict:
            continue
        category = crumb.get("category")
        if type(category) is not str:
            continue
        if any(category == name or category.startswith(name + ".")
               for name in ("httplib", "httpx", "httpcore")):
            continue
        kept.append(crumb)
    # Discard unexpected container fields rather than forwarding unknown content.
    result["breadcrumbs"] = {"values": kept}
    return result
