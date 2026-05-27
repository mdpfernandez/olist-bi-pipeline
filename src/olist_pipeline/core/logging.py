"""Structured logging built on structlog.

``configure_logging()`` wires structlog once per process; ``get_logger()``
hands out a bound logger for a module. Output is human-readable in ``console``
mode and machine-parseable in ``json`` mode (used inside Lambda).
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.typing import FilteringBoundLogger, Processor

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_logging(*, level: str = "INFO", fmt: str = "console") -> None:
    """Configure structlog process-wide. Safe to call more than once.

    An unrecognised ``level`` falls back to ``INFO`` rather than raising.
    """
    log_level = _LEVELS.get(level.upper(), logging.INFO)

    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    """Return a bound logger namespaced to ``name``."""
    return structlog.get_logger(name)
