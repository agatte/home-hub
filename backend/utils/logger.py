"""
Logging configuration — file (rotating JSON) + console (text) output.
"""
import ipaddress
import logging
import re
import sys
from logging.handlers import RotatingFileHandler

import httpx
from pythonjsonlogger.json import JsonFormatter

from backend.config import LOG_DIR, settings
from backend.services.tracing import request_id_var

# 5 MB per file, keep 3 old backups (20 MB total max)
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


class RequestContextFilter(logging.Filter):
    """Stamp the current request_id (if any) onto every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def suppress_hue_library_logging() -> None:
    """Silence pinned phue2==0.0.4's exact logger before Bridge.connect.

    It emits credentials/URLs even at INFO and on request failures. Disabling
    at the source also bypasses its own handlers, root propagation and lastResort,
    regardless of configured levels. Do not replace this with a home_hub filter.
    This does not sanitize other loggers, direct handler/telemetry calls, earlier
    records, later reconfiguration, or future library versions/child loggers.
    """
    logging.getLogger("phue_modern").disabled = True


def _hue_host() -> str | None:
    """Accept only a bare IP/DNS host, never a URL or credential-bearing value."""
    value = getattr(settings, "HUE_BRIDGE_IP", None)
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        return ipaddress.ip_address(value).compressed.lower()
    except ValueError:
        host = value.lower().removesuffix(".")
        if len(host) <= 253 and all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in host.split(".")
        ):
            return host
        return None


class HueHTTPXFilter(logging.Filter):
    """Reject bridge URL records before Logger.callHandlers (including Sentry).

    Only structured URL.host is inspected; no URL/exception is rendered. Unknown
    request-summary shapes/config fail closed. Unrelated diagnostics are retained.
    This covers the pinned emitting logger, not children, direct telemetry, earlier
    records or later filter removal. HTTPcore traces are a separate review surface.
    """

    _homehub_hue_httpx_filter = True

    def filter(self, record: logging.LogRecord) -> bool:
        summary = isinstance(record.msg, str) and record.msg.startswith("HTTP Request:")
        host = _hue_host()
        args = record.args
        if summary and not (
            record.msg == 'HTTP Request: %s %s "%s %d %s"'
            and isinstance(args, tuple) and len(args) == 5
            and isinstance(args[1], httpx.URL)
        ):
            return False
        values = args.values() if isinstance(args, dict) else args if isinstance(args, tuple) else ()
        found = False
        try:
            for value in values:
                if isinstance(value, httpx.URL):
                    found = True
                    request_host = value.host.lower().removesuffix(".")
                    try:
                        request_host = ipaddress.ip_address(request_host.strip("[]")).compressed.lower()
                    except ValueError:
                        pass  # Preserve normalized DNS hostnames.
                    if not host or not request_host or request_host == host:
                        return False
        except Exception:
            # Classification failure must not render the record or exception.
            return False
        return not summary or (found and host is not None)


def suppress_hue_httpx_logging() -> None:
    """Idempotently guard the exact emitting logger, without changing levels."""
    emitting_logger = logging.getLogger("httpx")
    if not any(getattr(f, "_homehub_hue_httpx_filter", False) for f in emitting_logger.filters):
        emitting_logger.addFilter(HueHTTPXFilter())


# Pinned httpcore==1.0.9 Trace emitters. Upgrade gate: re-audit emitter names
# and preformatted exception/header traces before changing the dependency.
_HTTPCORE_EMITTERS = (
    "httpcore.connection", "httpcore.http11", "httpcore.http2",
    "httpcore.proxy", "httpcore.socks",
)


class HTTPcoreTraceFilter(logging.Filter):
    """Drop DEBUG at emission before callHandlers/Sentry; never render payloads."""

    _homehub_httpcore_trace_filter = True

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno != logging.DEBUG


def suppress_httpcore_debug_logging() -> None:
    """Guard exact pinned emitters, preserving INFO+ and unrelated loggers."""
    for name in _HTTPCORE_EMITTERS:
        emitter = logging.getLogger(name)
        if not any(getattr(f, "_homehub_httpcore_trace_filter", False)
                   for f in emitter.filters):
            emitter.addFilter(HTTPcoreTraceFilter())


def setup_logging() -> logging.Logger:
    """
    Configure application-wide logging.

    Console gets human-readable text; file gets structured JSON
    for machine parsing (jq, log aggregation, alerting). Both
    handlers carry a RequestContextFilter so the request_id from
    the active ContextVar lands on every record.

    Returns:
        Root logger for the application.
    """
    suppress_hue_library_logging()
    suppress_hue_httpx_logging()
    suppress_httpcore_debug_logging()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("home_hub")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    context_filter = RequestContextFilter()

    # Console handler — human-readable text. The [%(request_id)s] prefix
    # shows "[None]" for records emitted outside any request context;
    # acceptable readability cost for end-to-end traceability.
    text_formatter = logging.Formatter(
        fmt="[%(request_id)s] %(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(text_formatter)
    console_handler.addFilter(context_filter)
    logger.addHandler(console_handler)

    # Rotating file handler — structured JSON, caps disk at ~20 MB
    json_formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(funcName)s %(lineno)d %(request_id)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        LOG_DIR / "home_hub.log",
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(json_formatter)
    file_handler.addFilter(context_filter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging()
