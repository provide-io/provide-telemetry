# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutation-testing mutants in logger/core.py and metrics/provider.py."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger import core as core_mod
from undef.telemetry.logger.core import (
    _get_level,
    _reset_logging_for_tests,
    _TraceWrapper,
    shutdown_logging,
)
from undef.telemetry.metrics import provider as provider_mod
from undef.telemetry.metrics.provider import get_meter

# ── _get_level case sensitivity ──────────────────────────────────────


class TestGetLevelCaseSensitive:
    def test_trace_uppercase_returns_5(self) -> None:
        """Kills: `'TRACE'` → `'XXTRACEXX'` or `'trace'`."""
        assert _get_level("TRACE") == 5

    def test_trace_lowercase_returns_info(self) -> None:
        """If the string is 'trace' (lowercase), it should NOT match the TRACE branch."""
        result = _get_level("trace")
        # 'trace' is not 'TRACE', so it falls through to getLevelName
        # getLevelName('trace') → 'Level trace' (not an int) → returns INFO
        assert result == logging.INFO

    def test_trace_mixed_case_returns_info(self) -> None:
        result = _get_level("Trace")
        assert result == logging.INFO


# ── _reset_logging_for_tests exact values ────────────────────────────


class TestResetLoggingExactValues:
    def test_configured_set_to_false_not_none(self) -> None:
        """Kills: `_configured = False` → `None`."""
        core_mod._configured = True
        _reset_logging_for_tests()
        assert core_mod._configured is False
        assert core_mod._configured is not None

    def test_active_config_set_to_none_not_empty_string(self) -> None:
        """Kills: `_active_config = None` → `''`."""
        core_mod._active_config = TelemetryConfig()
        _reset_logging_for_tests()
        assert core_mod._active_config is None
        assert core_mod._active_config != ""

    def test_otel_log_provider_set_to_none_not_empty_string(self) -> None:
        """Kills: `_otel_log_provider = None` → `''`."""
        core_mod._otel_log_provider = object()
        _reset_logging_for_tests()
        assert core_mod._otel_log_provider is None
        assert core_mod._otel_log_provider != ""


# ── shutdown_logging exact values ────────────────────────────────────


class TestShutdownLoggingExactValues:
    def test_configured_set_to_false_not_none(self) -> None:
        """Kills: `_configured = False` → `None`."""
        core_mod._configured = True
        core_mod._active_config = TelemetryConfig()
        core_mod._otel_log_provider = None
        shutdown_logging()
        assert core_mod._configured is False
        assert core_mod._configured is not None

    def test_active_config_set_to_none(self) -> None:
        """Kills: `_active_config = None` → `''`."""
        core_mod._configured = True
        core_mod._active_config = TelemetryConfig()
        core_mod._otel_log_provider = None
        shutdown_logging()
        assert core_mod._active_config is None
        assert core_mod._active_config != ""


# ── trace() and→or mutation ──────────────────────────────────────────


class TestTraceAndVsOr:
    def test_trace_does_not_call_debug_when_active_config_is_none(self) -> None:
        """Kills: `_active_config is not None and ...` → `or`.
        When _active_config is None, trace() must NOT call _logger.debug()."""
        mock_logger = Mock()
        wrapper = _TraceWrapper(mock_logger)
        core_mod._active_config = None
        wrapper.trace("test.event")
        mock_logger.debug.assert_not_called()

    def test_trace_does_not_call_when_level_is_not_trace(self) -> None:
        mock_logger = Mock()
        wrapper = _TraceWrapper(mock_logger)
        core_mod._active_config = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "INFO"})
        wrapper.trace("test.event")
        mock_logger.debug.assert_not_called()

    def test_trace_calls_debug_when_config_and_level_match(self) -> None:
        mock_logger = Mock()
        wrapper = _TraceWrapper(mock_logger)
        core_mod._active_config = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "TRACE"})
        wrapper.trace("test.event", key="val")
        mock_logger.debug.assert_called_once_with("test.event", _trace=True, key="val")


# ── metrics/provider.py: get_meter caching ─────────────────────────


class TestGetMeterCaching:
    def test_get_meter_caches_meter_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `_meters[meter_name] = meter` → `= None`.
        After first call, second call should return the same meter from cache."""
        provider_mod._meters.clear()
        meter_obj = Mock()
        mock_otel = Mock()
        mock_otel.get_meter.return_value = meter_obj
        monkeypatch.setattr(provider_mod, "_HAS_OTEL_METRICS", True)
        monkeypatch.setattr(provider_mod, "_load_otel_metrics_api", lambda: mock_otel)

        first = get_meter("custom.meter")
        assert first is meter_obj
        assert mock_otel.get_meter.call_count == 1

        # Second call should use cache, not call get_meter again
        second = get_meter("custom.meter")
        assert second is meter_obj
        assert second is first
        # If the cache stored None, get_meter would be called again
        assert mock_otel.get_meter.call_count == 1
