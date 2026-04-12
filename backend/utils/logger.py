"""
Logging configuration — file (rotating JSON) + console (text) output.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from pythonjsonlogger.json import JsonFormatter

from backend.config import LOG_DIR, settings

# 5 MB per file, keep 3 old backups (20 MB total max)
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


def setup_logging() -> logging.Logger:
    """
    Configure application-wide logging.

    Console gets human-readable text; file gets structured JSON
    for machine parsing (jq, log aggregation, alerting).

    Returns:
        Root logger for the application.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("home_hub")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # Console handler — human-readable text
    text_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(text_formatter)
    logger.addHandler(console_handler)

    # Rotating file handler — structured JSON, caps disk at ~20 MB
    json_formatter = JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s %(funcName)s %(lineno)d",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        LOG_DIR / "home_hub.log",
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(json_formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging()
