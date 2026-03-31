# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in logger/core.py and metrics/provider.py."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import Mock

import pytest
import structlog

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger.core import (
    TRACE,
    _get_level,
    _make_filtering_bound_logger,
    _reset_logging_for_tests,
    _TraceWrapper,
    configure_logging,
    is_trace_enabled,
    shutdown_logging,
)
from provide.telemetry.metrics import provider as provider_mod
from provide.telemetry.metrics.provider import get_meter

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
        core_mod._active_config = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "INFO"})
        wrapper.trace("test.event")
        mock_logger.debug.assert_not_called()

    def test_trace_calls_trace_when_config_and_level_match(self) -> None:
        mock_logger = Mock()
        wrapper = _TraceWrapper(mock_logger)
        core_mod._active_config = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "TRACE"})
        wrapper.trace("test.event", key="val")
        mock_logger.trace.assert_called_once_with("test.event", key="val")


# ── metrics/provider.py: get_meter caching ─────────────────────────


class TestGetMeterCaching:
    def test_get_meter_caches_meter_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: `_meters[meter_name] = meter` → `= None`.
        After first call, second call should return the same meter from cache."""
        provider_mod._meters.clear()
        provider_mod._meter_provider = True  # gate: get_meter() requires non-None provider
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


# ── configure_logging default force=False ────────────────────────────


class TestConfigureLoggingForceDefault:
    def test_second_call_without_force_is_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills mutant: force: bool = False → True.

        If force defaults to True, every call re-runs structlog.configure.
        We verify the second call with same config is a no-op.
        """
        _reset_logging_for_tests()
        cfg = TelemetryConfig()
        configure_logging(cfg)  # First call — configures

        reconfigure_calls: list[object] = []
        monkeypatch.setattr(structlog, "configure", lambda **kw: reconfigure_calls.append(kw))
        configure_logging(cfg)  # Second call without force — must be no-op
        assert reconfigure_calls == []


# ── configure_logging effective_level computation ────────────────────────────


class TestConfigureLoggingEffectiveLevel:
    def test_effective_level_is_minimum_of_default_and_module_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: effective_level < comparison mutation.

        When default=WARNING and asyncio=DEBUG, effective_level must be DEBUG so
        the FilteringBoundLogger allows debug events to reach the _LevelFilter
        processor, which then applies per-module thresholds.
        """
        _reset_logging_for_tests()
        monkeypatch.setattr(core_mod, "_build_handlers", lambda _cfg, _lvl: [])
        configure_calls: list[dict[str, Any]] = []
        monkeypatch.setattr(structlog, "configure", lambda **kw: configure_calls.append(kw))

        cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "WARNING", "PROVIDE_LOG_MODULE_LEVELS": "asyncio=DEBUG"})
        configure_logging(cfg)

        assert len(configure_calls) == 1
        wrapper_cls = configure_calls[0]["wrapper_class"]
        # Effective level is DEBUG, so is_debug_enabled() must return True
        assert wrapper_cls.is_debug_enabled(None) is True
        _reset_logging_for_tests()  # restore clean state so structlog isn't left unconfigured


# ── is_trace_enabled() with None config ──────────────────────────────────────


class TestIsTraceEnabledNoneConfig:
    def test_returns_true_when_active_config_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: return True → return False in is_trace_enabled() unconfigured branch."""
        monkeypatch.setattr(core_mod, "_active_config", None)
        assert is_trace_enabled() is True

    def test_returns_true_at_trace_level_with_active_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills: active.logging.level → None; <= → < in is_trace_enabled().

        At TRACE level, _get_level('TRACE') = 5. 5 <= 5 (TRACE) = True.
        With active.logging.level→None: _get_level(None) = INFO(20). 20 <= 5 = False.
        With <= → <: 5 < 5 = False.
        """
        cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "TRACE"})
        monkeypatch.setattr(core_mod, "_active_config", cfg)
        assert is_trace_enabled() is True


# ── _TraceWrapper.is_trace_enabled() delegation ──────────────────────────────


class TestTraceWrapperIsTraceEnabled:
    def test_delegates_true_to_inner_logger(self) -> None:
        """Kills: is_trace_enabled delegation — True path."""
        mock_logger = Mock()
        mock_logger.is_trace_enabled.return_value = True
        wrapper = _TraceWrapper(mock_logger)
        assert wrapper.is_trace_enabled() is True

    def test_delegates_false_to_inner_logger(self) -> None:
        """Kills: is_trace_enabled delegation — False path."""
        mock_logger = Mock()
        mock_logger.is_trace_enabled.return_value = False
        wrapper = _TraceWrapper(mock_logger)
        assert wrapper.is_trace_enabled() is False


# ── _make_filtering_bound_logger() ───────────────────────────────────────────


class TestMakeFilteringBoundLogger:
    @pytest.fixture(autouse=True)
    def reset_structlog_filtering_classes(self) -> Any:
        """Reset structlog's cached filtering bound logger classes to a clean state.

        structlog.make_filtering_bound_logger() returns a shared class from a
        module-level dict (LEVEL_TO_FILTERING_LOGGER).  Our code mutates that
        class with setattr(), so subsequent calls in the same process see the
        already-mutated state — masking key-name mutations in _standard_levels.
        This fixture restores debug/info/warning/error on the affected level
        classes to structlog's original _nop before each test.
        """
        import structlog._native as _native

        _nop = _native._nop
        levels_and_attrs: list[tuple[Any, str]] = [
            (_native.BoundLoggerFilteringAtWarning, "debug"),
            (_native.BoundLoggerFilteringAtWarning, "info"),
            (_native.BoundLoggerFilteringAtError, "warning"),
            (_native.BoundLoggerFilteringAtCritical, "error"),
        ]
        for cls, attr in levels_and_attrs:
            setattr(cls, attr, _nop)
        yield
        for cls, attr in levels_and_attrs:
            setattr(cls, attr, _nop)

    def test_is_debug_enabled_true_at_debug_level(self) -> None:
        """Kills: _debug_ok/_trace_ok swap — is_debug_enabled must be True at DEBUG."""
        cls = _make_filtering_bound_logger(logging.DEBUG)
        assert getattr(cls, "is_debug_enabled")(None) is True  # noqa: B009

    def test_is_trace_enabled_true_at_trace_level(self) -> None:
        """Kills: level <= TRACE boundary — is_trace_enabled must be True at TRACE."""
        cls = _make_filtering_bound_logger(TRACE)
        assert getattr(cls, "is_trace_enabled")(None) is True  # noqa: B009

    def test_is_trace_enabled_false_at_debug_level(self) -> None:
        """Kills: _debug_ok/_trace_ok swap and boundary — TRACE not enabled at DEBUG."""
        cls = _make_filtering_bound_logger(logging.DEBUG)
        assert getattr(cls, "is_trace_enabled")(None) is False  # noqa: B009

    def test_trace_method_calls_debug_with_trace_marker_and_kwargs(self) -> None:
        """Kills: **kw removal from _trace() — kwargs must be forwarded to debug()."""
        cls = _make_filtering_bound_logger(TRACE)
        mock_self = Mock()
        getattr(cls, "trace")(mock_self, "event.test", key="val")  # noqa: B009
        mock_self.debug.assert_called_once_with("event.test", _trace=True, key="val")

    def test_debug_method_is_permissive_nop_at_warning_level(self) -> None:
        """Kills: max() → min() for structlog_level; 'debug' key name mutations.

        max(WARNING=30, DEBUG=10) = 30, so the permissive_nop loop replaces debug().
        With min(), structlog_level=10 and the loop condition (10 < 10) is False,
        so debug() is NOT replaced and would route through the pipeline.
        """
        cls = _make_filtering_bound_logger(logging.WARNING)
        assert getattr(cls, "debug").__name__ == "_permissive_nop"  # noqa: B009

    def test_info_method_is_permissive_nop_at_warning_level(self) -> None:
        """Kills: 'info' key name mutations in _standard_levels."""
        cls = _make_filtering_bound_logger(logging.WARNING)
        assert getattr(cls, "info").__name__ == "_permissive_nop"  # noqa: B009

    def test_warning_method_is_permissive_nop_at_error_level(self) -> None:
        """Kills: 'warning' key name mutations in _standard_levels."""
        cls = _make_filtering_bound_logger(logging.ERROR)
        assert getattr(cls, "warning").__name__ == "_permissive_nop"  # noqa: B009

    def test_error_method_is_permissive_nop_at_critical_level(self) -> None:
        """Kills: 'error' key name mutations in _standard_levels."""
        cls = _make_filtering_bound_logger(logging.CRITICAL)
        assert getattr(cls, "error").__name__ == "_permissive_nop"  # noqa: B009


# ── configure_logging sanitize config propagation ──────────────────────


class TestConfigureLoggingSanitizeConfig:
    def test_sanitize_config_propagated_not_replaced_with_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills mutmut_33: sanitize_sensitive_fields(config.logging.sanitize) -> sanitize_sensitive_fields(None).

        When sanitize is True in config, the sanitize_sensitive_fields processor
        must receive True, not None. With None (falsy), sanitization is skipped.
        """
        _reset_logging_for_tests()
        monkeypatch.setattr(core_mod, "_build_handlers", lambda _cfg, _lvl: [])

        # Track what sanitize_sensitive_fields receives
        from provide.telemetry.logger import processors as proc_mod

        original_ssf = proc_mod.sanitize_sensitive_fields
        captured_args: list[object] = []

        def tracking_ssf(enabled: object, max_depth: int = 8) -> Any:
            captured_args.append(enabled)
            return original_ssf(enabled, max_depth)  # type: ignore[arg-type]

        monkeypatch.setattr(core_mod, "sanitize_sensitive_fields", tracking_ssf)

        cfg = TelemetryConfig.from_env({"PROVIDE_LOG_SANITIZE": "true"})
        configure_logging(cfg, force=True)

        assert len(captured_args) == 1
        assert captured_args[0] is True  # must be True, not None
        _reset_logging_for_tests()
