# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for emergency fallback logging configuration."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from unittest.mock import patch

import pytest
import structlog

from provide.telemetry.config import TelemetryConfig
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
