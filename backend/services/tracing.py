"""
Request-scoped correlation IDs.

Every HTTP request and every WebSocket connection gets a short unique
ID stored in a ContextVar. A logging Filter copies it onto each
LogRecord so existing logger.info() / logger.error() calls auto-tag
their output without needing extra={...} at every site.

The ID also rides back to the client via the X-Request-ID response
header (HTTP) or the connection_status payload (WebSocket).
"""
import uuid
from contextvars import ContextVar

# 12 hex chars = 48 bits of entropy: collision-resistant for our scale,
# short enough to grep and copy/paste into a support ticket.
_ID_LENGTH = 12

# Cap on caller-supplied IDs we'll trust. Above this we fall back to a
# server-generated value — defends the log surface against a noisy
# client filling records with megabyte-long correlation strings.
MAX_INBOUND_LENGTH = 64

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    """Generate a fresh correlation ID."""
    return uuid.uuid4().hex[:_ID_LENGTH]


def coerce_inbound_id(raw: str | None) -> str:
    """
    Validate a client-supplied ID, or generate one if it's missing /
    malformed. Accepts printable ASCII up to MAX_INBOUND_LENGTH chars.
    """
    if not raw:
        return new_request_id()
    if len(raw) > MAX_INBOUND_LENGTH:
        return new_request_id()
    if not raw.isprintable() or any(c.isspace() for c in raw):
        return new_request_id()
    return raw
