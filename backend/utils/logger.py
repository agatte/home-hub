"""
Logging configuration — file (rotating) + console output.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler

from backend.config import LOG_DIR, settings

# 5 MB per file, keep 3 old backups (20 MB total max)
_MAX_LOG_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3


def setup_logging() -> logging.Logger:
    """
    Configure application-wide logging.

    Returns:
        Root logger for the application.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("home_hub")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Rotating file handler — caps disk usage at ~20 MB
    file_handler = RotatingFileHandler(
        LOG_DIR / "home_hub.log",
        maxBytes=_MAX_LOG_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


logger = setup_logging()
