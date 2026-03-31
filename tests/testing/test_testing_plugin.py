# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for the provide.telemetry.testing module."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import structlog

from provide.telemetry.testing import (
    configure_caplog_for_structlog,
    reset_telemetry_state,
    reset_trace_context,
)
from provide.telemetry.tracing.context import get_trace_context, set_trace_context

if TYPE_CHECKING:
    import pytest


def test_caplog_captures_structlog_info(caplog: pytest.LogCaptureFixture) -> None:
    """structlog INFO messages appear in caplog after configure_caplog_for_structlog."""
    configure_caplog_for_structlog()
    log = structlog.get_logger("test.caplog")
    with caplog.at_level(logging.DEBUG):
        log.info("hello.from.structlog")
    assert "hello.from.structlog" in caplog.text


def test_caplog_captures_structlog_debug(caplog: pytest.LogCaptureFixture) -> None:
    """structlog DEBUG messages are NOT swallowed after configure_caplog_for_structlog."""
    configure_caplog_for_structlog()
    log = structlog.get_logger("test.caplog.debug")
    with caplog.at_level(logging.DEBUG):
        log.debug("debug.message.here")
    assert "debug.message.here" in caplog.text


def test_configure_caplog_for_structlog_applies_defaults() -> None:
    """The one-shot helper applies the expected pipeline."""
    structlog.reset_defaults()
    configure_caplog_for_structlog()

    cfg = structlog.get_config()
    assert len(cfg["processors"]) == 2
    assert cfg["cache_logger_on_first_use"] is False


def test_configure_caplog_for_structlog_accepts_overrides() -> None:
    """Overrides are forwarded to structlog.configure()."""
    structlog.reset_defaults()
    configure_caplog_for_structlog(cache_logger_on_first_use=True)

    cfg = structlog.get_config()
    assert cfg["cache_logger_on_first_use"] is True


def test_reset_telemetry_state_clears_structlog() -> None:
    """reset_telemetry_state resets structlog config."""
    configure_caplog_for_structlog()
    cfg_before = structlog.get_config()
    assert len(cfg_before["processors"]) == 2

    reset_telemetry_state()
    # After reset, structlog reverts to defaults (different processor list)
    cfg_after = structlog.get_config()
    assert cfg_after != cfg_before


def test_configure_caplog_colors_disabled() -> None:
    """colors=False is critical so caplog.text has no ANSI escapes."""
    configure_caplog_for_structlog()
    cfg = structlog.get_config()
    renderer = cfg["processors"][-1]
    assert isinstance(renderer, structlog.dev.ConsoleRenderer)
    assert renderer._colors is False


def test_reset_trace_context_clears_ids() -> None:
    """reset_trace_context clears trace and span IDs."""
    set_trace_context("abc123", "span456")
    ctx = get_trace_context()
    assert ctx["trace_id"] == "abc123"

    reset_trace_context()
    ctx = get_trace_context()
    assert ctx["trace_id"] is None
    assert ctx["span_id"] is None
