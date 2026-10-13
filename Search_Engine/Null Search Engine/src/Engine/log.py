"""Logging setup. Query text is never logged unless NULL_SEARCH_LOG_QUERIES=1."""
from __future__ import annotations

import logging
import sys

ROOT = "nullsearch"


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT}.{name}")


def configure_logging(level: str = "INFO") -> None:
    logger = logging.getLogger(ROOT)
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level, logging.INFO))
    logger.propagate = False


def q_for_log(query: str, enabled: bool) -> str:
    """Return the query for log lines, or a length-only placeholder when privacy mode is on."""
    return repr(query[:80]) if enabled else f"<{len(query)} chars>"
