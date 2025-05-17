"""Shared utility functions for the Actual Budget Normalizer project."""

import logging
from datetime import UTC, datetime
from pathlib import Path


def get_logger(name: str) -> logging.Logger:
    """Get a logger with a standard format for the project."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def ensure_dir(path: str | Path) -> None:
    """Ensure a directory exists (like mkdir -p)."""
    Path(path).mkdir(parents=True, exist_ok=True)


def safe_cast(val: object, to_type: type, default: object = None) -> object:
    """Safely cast a value to a type, returning default on failure."""
    try:
        return to_type(val)
    except (ValueError, TypeError):
        return default


def utcnow_iso() -> str:
    """Get the current UTC time as an ISO8601 string."""
    return datetime.now(UTC).isoformat()
