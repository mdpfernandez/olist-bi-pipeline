"""Unit tests for olist_pipeline.core.logging."""

from __future__ import annotations

import pytest

from olist_pipeline.core.logging import configure_logging, get_logger


@pytest.mark.unit
def test_configure_logging_and_emit_does_not_raise() -> None:
    configure_logging(level="INFO", fmt="json")
    log = get_logger("test.logging")
    log.info("test.event", key="value")


@pytest.mark.unit
def test_unknown_level_falls_back_to_info() -> None:
    configure_logging(level="NONSENSE", fmt="console")
    log = get_logger("test.logging")
    log.warning("still.works")
