# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Race-condition regression tests for :mod:`provide.telemetry.logger.core`.

Exercises the path where ``is_debug_enabled`` / ``is_trace_enabled`` are
called concurrently with ``shutdown_logging`` — the readers must take the
module lock so a writer cannot swap ``_active_config`` to ``None`` between
the truthy check and the attribute access.
"""

from __future__ import annotations

import threading
import time

from provide.telemetry.config import LoggingConfig, TelemetryConfig
from provide.telemetry.logger.core import (
    _reset_logging_for_tests,
    configure_logging,
    is_debug_enabled,
    is_trace_enabled,
    shutdown_logging,
)


def _debug_config() -> TelemetryConfig:
    return TelemetryConfig(logging=LoggingConfig(level="DEBUG"))


def test_is_debug_enabled_safe_under_shutdown_race() -> None:
    """Concurrent ``is_debug_enabled`` readers must never raise AttributeError.

    Historically the readers snapshotted ``_active_config`` outside the lock,
    so a parallel ``shutdown_logging`` could set it to ``None`` between the
    truthy check and ``active.logging.level``.  The fix is to snapshot under
    the lock; this test fails loudly if that regresses.
    """
    configure_logging(_debug_config())
    stop = threading.Event()
    errors: list[BaseException] = []
    observed_values: list[bool] = []

    def _reader() -> None:
        while not stop.is_set():
            try:
                observed_values.append(is_debug_enabled())
            except BaseException as exc:  # pragma: no cover — defensive
                errors.append(exc)
                return

    def _flapper() -> None:
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            shutdown_logging()
            configure_logging(_debug_config())
        stop.set()

    readers = [threading.Thread(target=_reader) for _ in range(4)]
    flapper = threading.Thread(target=_flapper)
    try:
        for t in readers:
            t.start()
        flapper.start()
        flapper.join()
        for t in readers:
            t.join()
    finally:
        # Guarantee a clean baseline for the autouse reset_logger_state
        # fixture by shutting down and resetting state unconditionally
        # (even if an assertion below raises).  Leaving _otel_log_provider
        # set would pollute subsequent tests in the same worker.
        shutdown_logging()
        _reset_logging_for_tests()

    assert errors == []
    # Every read is either True (configured) or True (unconfigured fallback)
    # because the default path returns True in both cases.  We mainly assert
    # the reader returned a bool every time — not a raised AttributeError.
    assert observed_values  # at least one read happened
    assert all(isinstance(v, bool) for v in observed_values)


def test_is_trace_enabled_safe_under_shutdown_race() -> None:
    """Same guarantee as debug, applied to the trace reader."""
    configure_logging(TelemetryConfig(logging=LoggingConfig(level="TRACE")))
    stop = threading.Event()
    errors: list[BaseException] = []

    def _reader() -> None:
        while not stop.is_set():
            try:
                is_trace_enabled()
            except BaseException as exc:  # pragma: no cover — defensive
                errors.append(exc)
                return

    def _flapper() -> None:
        deadline = time.monotonic() + 0.2
        while time.monotonic() < deadline:
            shutdown_logging()
            configure_logging(TelemetryConfig(logging=LoggingConfig(level="TRACE")))
        stop.set()

    reader = threading.Thread(target=_reader)
    flapper = threading.Thread(target=_flapper)
    try:
        reader.start()
        flapper.start()
        flapper.join()
        reader.join()
    finally:
        shutdown_logging()
        _reset_logging_for_tests()

    assert errors == []


def test_is_debug_enabled_returns_true_when_unconfigured() -> None:
    """Readers must fall back to True when no config has been installed."""
    _reset_logging_for_tests()
    assert is_debug_enabled() is True
    assert is_trace_enabled() is True
