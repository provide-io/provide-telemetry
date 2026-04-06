# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for emergency fallback logging configuration."""

from __future__ import annotations

import logging
import sys
import warnings
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
import structlog

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger.core import (
    _reset_logging_for_tests,
    _setup_emergency_fallback,
    configure_logging,
    get_logger,
    shutdown_logging,
)


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    _reset_logging_for_tests()
    yield
    _reset_logging_for_tests()


class TestSetupEmergencyFallback:
    def test_fallback_configures_structlog(self) -> None:
        exc = RuntimeError("test failure")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            _setup_emergency_fallback(exc)
        # structlog should be usable after fallback
        logger = structlog.get_logger("test")
        assert logger is not None

    def test_fallback_emits_runtime_warning(self) -> None:
        exc = RuntimeError("connection refused")
        with pytest.warns(RuntimeWarning, match="logging setup failed.*connection refused"):
            _setup_emergency_fallback(exc)

    def test_get_logger_works_after_fallback(self) -> None:
        exc = RuntimeError("broken")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            _setup_emergency_fallback(exc)
        logger = get_logger("test-fallback")
        assert logger is not None

    def test_shutdown_works_after_fallback(self) -> None:
        exc = RuntimeError("broken")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            _setup_emergency_fallback(exc)
        # Should not raise
        shutdown_logging()


class TestEmergencyFallbackMutations:
    """Kill mutation survivors in _setup_emergency_fallback."""

    def test_fallback_sets_configured_to_true(self) -> None:
        """Kills: _configured = True -> _configured = False."""
        exc = RuntimeError("fail")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            _setup_emergency_fallback(exc)
        assert core_mod._configured is True

    def test_fallback_sets_active_config_to_none(self) -> None:
        """Kills: _active_config = None -> _active_config = ''."""
        core_mod._active_config = TelemetryConfig()
        exc = RuntimeError("fail")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            _setup_emergency_fallback(exc)
        assert core_mod._active_config is None

    def test_fallback_warning_message_contains_emergency_stderr(self) -> None:
        """Kills: string literal mutations in warning message."""
        exc = RuntimeError("specific-error-text")
        with pytest.warns(RuntimeWarning, match="emergency stderr fallback"):
            _setup_emergency_fallback(exc)

    def test_fallback_warning_message_contains_setup_failed(self) -> None:
        """Kills: 'logging setup failed' string mutation."""
        exc = RuntimeError("x")
        with pytest.warns(RuntimeWarning, match="logging setup failed"):
            _setup_emergency_fallback(exc)

    def test_fallback_warning_includes_exception_text(self) -> None:
        """Kills: f-string {exc} mutation."""
        exc = RuntimeError("unique-marker-12345")
        with pytest.warns(RuntimeWarning, match="unique-marker-12345"):
            _setup_emergency_fallback(exc)

    def test_fallback_uses_console_renderer_with_colors_false(self) -> None:
        """Kills: colors=False -> colors=True/None."""
        configure_calls: list[dict[str, Any]] = []

        def spy_configure(**kwargs: Any) -> None:
            configure_calls.append(kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(structlog, "configure", side_effect=spy_configure):
                _setup_emergency_fallback(RuntimeError("fail"))

        assert len(configure_calls) == 1
        processors = configure_calls[0]["processors"]
        renderer = processors[-1]
        assert isinstance(renderer, structlog.dev.ConsoleRenderer)
        # Verify colors=False by rendering and checking no ANSI codes
        test_output = renderer(None, "test", {"event": "hello", "level": "info"})
        assert "\033" not in test_output  # No ANSI escape codes when colors=False

    def test_fallback_uses_warning_level_filter(self) -> None:
        """Kills: logging.WARNING -> logging.INFO or other level."""
        configure_calls: list[dict[str, Any]] = []

        def spy_configure(**kwargs: Any) -> None:
            configure_calls.append(kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(structlog, "configure", side_effect=spy_configure):
                _setup_emergency_fallback(RuntimeError("fail"))

        assert len(configure_calls) == 1
        wrapper_cls = configure_calls[0]["wrapper_class"]
        # At WARNING level, make_filtering_bound_logger filters debug/info
        # The wrapper class should have the class name indicating WARNING level
        assert wrapper_cls is structlog.make_filtering_bound_logger(logging.WARNING)

    def test_fallback_uses_print_logger_factory_to_stderr(self) -> None:
        """Kills: file=sys.stderr -> file=sys.stdout or None."""
        configure_calls: list[dict[str, Any]] = []

        def spy_configure(**kwargs: Any) -> None:
            configure_calls.append(kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(structlog, "configure", side_effect=spy_configure):
                _setup_emergency_fallback(RuntimeError("fail"))

        factory = configure_calls[0]["logger_factory"]
        assert isinstance(factory, structlog.PrintLoggerFactory)
        assert factory._file is sys.stderr

    def test_fallback_cache_logger_on_first_use_is_false(self) -> None:
        """Kills: cache_logger_on_first_use=False -> True."""
        configure_calls: list[dict[str, Any]] = []

        def spy_configure(**kwargs: Any) -> None:
            configure_calls.append(kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(structlog, "configure", side_effect=spy_configure):
                _setup_emergency_fallback(RuntimeError("fail"))

        assert configure_calls[0]["cache_logger_on_first_use"] is False

    def test_fallback_processors_include_add_log_level(self) -> None:
        """Kills: processor list mutation (removing add_log_level)."""
        configure_calls: list[dict[str, Any]] = []

        def spy_configure(**kwargs: Any) -> None:
            configure_calls.append(kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(structlog, "configure", side_effect=spy_configure):
                _setup_emergency_fallback(RuntimeError("fail"))

        processors = configure_calls[0]["processors"]
        assert structlog.processors.add_log_level in processors

    def test_fallback_processors_include_timestamper_with_iso_format(self) -> None:
        """Kills: TimeStamper(fmt='iso') mutations to fmt=None/'XXisoXX'/'ISO'."""
        configure_calls: list[dict[str, Any]] = []

        def spy_configure(**kwargs: Any) -> None:
            configure_calls.append(kwargs)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            with patch.object(structlog, "configure", side_effect=spy_configure):
                _setup_emergency_fallback(RuntimeError("fail"))

        processors = configure_calls[0]["processors"]
        # Should have exactly 3 processors
        assert len(processors) == 3
        # Second processor should be a TimeStamper with iso format
        ts_proc = processors[1]
        assert isinstance(ts_proc, structlog.processors.TimeStamper)
        # Verify fmt="iso" by running the processor and checking output format
        test_dict: dict[str, Any] = {"event": "test"}
        result = ts_proc(None, "info", test_dict)
        ts_value = result.get("timestamp", "")
        # ISO format timestamps contain "T" and end with "+00:00" or "Z"
        assert "T" in str(ts_value), f"Timestamp {ts_value!r} is not ISO format"

    def test_fallback_warning_is_runtime_warning_type(self) -> None:
        """Kills: RuntimeWarning -> UserWarning or other type."""
        exc = RuntimeError("fail")
        with pytest.warns(RuntimeWarning):
            _setup_emergency_fallback(exc)


class TestConfigureLoggingFallback:
    def test_configure_logging_catches_exception_and_falls_back(self) -> None:
        cfg = TelemetryConfig()
        with (
            patch(
                "provide.telemetry.logger.core._configure_logging_inner",
                side_effect=RuntimeError("provider init failed"),
            ),
            pytest.warns(RuntimeWarning, match="logging setup failed"),
        ):
            configure_logging(cfg, force=True)
        # Should still be configured (via fallback)
        logger = get_logger("post-fallback")
        assert logger is not None

    def test_configure_logging_normal_path_still_works(self) -> None:
        cfg = TelemetryConfig()
        configure_logging(cfg, force=True)
        logger = get_logger("normal")
        assert logger is not None

    def test_configure_logging_passes_exc_to_fallback_not_none(self) -> None:
        """Kills: _setup_emergency_fallback(exc) -> _setup_emergency_fallback(None)."""
        cfg = TelemetryConfig()
        captured_exc: list[Exception | None] = []
        original_fallback = core_mod._setup_emergency_fallback

        def spy_fallback(exc: Exception) -> None:
            captured_exc.append(exc)
            original_fallback(exc)

        with (
            patch(
                "provide.telemetry.logger.core._configure_logging_inner",
                side_effect=RuntimeError("specific-error-msg"),
            ),
            patch.object(core_mod, "_setup_emergency_fallback", side_effect=spy_fallback),
        ):
            configure_logging(cfg, force=True)

        assert len(captured_exc) == 1
        assert captured_exc[0] is not None
        assert isinstance(captured_exc[0], RuntimeError)
        assert "specific-error-msg" in str(captured_exc[0])

    def test_get_logger_passes_config_not_none(self) -> None:
        """Kills: configure_logging(TelemetryConfig.from_env()) -> configure_logging(None)."""
        captured_configs: list[TelemetryConfig | None] = []
        original_configure = core_mod.configure_logging

        def spy_configure(config: TelemetryConfig, **kwargs: Any) -> None:
            captured_configs.append(config)
            original_configure(config, **kwargs)

        with patch.object(core_mod, "configure_logging", side_effect=spy_configure):
            core_mod.get_logger("test")

        assert len(captured_configs) == 1
        assert captured_configs[0] is not None
        assert isinstance(captured_configs[0], TelemetryConfig)
