# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for :func:`provide.telemetry.resilience.bounded_provider_shutdown`."""

from __future__ import annotations

import threading
import time

import pytest

from provide.telemetry.resilience import bounded_provider_shutdown


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def force_flush(self) -> None:
        self.calls.append("force_flush")

    def shutdown(self) -> None:
        self.calls.append("shutdown")


def test_bounded_provider_shutdown_completes_and_orders_calls() -> None:
    provider = _RecordingProvider()
    assert bounded_provider_shutdown(provider, timeout_seconds=1.0) is True
    assert provider.calls == ["force_flush", "shutdown"]


def test_bounded_provider_shutdown_returns_true_when_provider_has_no_methods() -> None:
    class _Empty:
        pass

    assert bounded_provider_shutdown(_Empty(), timeout_seconds=1.0) is True


def test_bounded_provider_shutdown_skips_non_callable_attrs() -> None:
    class _NonCallable:
        force_flush = "not-callable"
        shutdown = 42

    # Must not raise even though attributes exist but aren't callable.
    assert bounded_provider_shutdown(_NonCallable(), timeout_seconds=1.0) is True


def test_bounded_provider_shutdown_propagates_exception_from_force_flush() -> None:
    class _Boom:
        def force_flush(self) -> None:
            raise RuntimeError("flush boom")

        def shutdown(self) -> None:  # pragma: no cover — never reached
            raise AssertionError("shutdown should not run when force_flush raises")

    with pytest.raises(RuntimeError, match="flush boom"):
        bounded_provider_shutdown(_Boom(), timeout_seconds=1.0)


def test_bounded_provider_shutdown_propagates_exception_from_shutdown() -> None:
    class _BoomOnShutdown:
        def force_flush(self) -> None:
            return

        def shutdown(self) -> None:
            raise RuntimeError("shutdown boom")

    with pytest.raises(RuntimeError, match="shutdown boom"):
        bounded_provider_shutdown(_BoomOnShutdown(), timeout_seconds=1.0)


def test_bounded_provider_shutdown_abandons_and_warns_on_timeout() -> None:
    """When force_flush exceeds the deadline, return False and emit a warning."""
    release = threading.Event()

    class _SlowProvider:
        def force_flush(self) -> None:
            # Block until released so the bounded wait must time out.
            release.wait(timeout=5.0)

        def shutdown(self) -> None:  # pragma: no cover — unreachable on timeout
            raise AssertionError("shutdown should not be invoked after timeout")

    provider = _SlowProvider()
    try:
        with pytest.warns(RuntimeWarning, match="exceeded .* deadline"):
            completed = bounded_provider_shutdown(provider, timeout_seconds=0.1)
        assert completed is False
    finally:
        # Let the abandoned daemon thread exit cleanly so pytest doesn't see it
        # still running at process exit.
        release.set()


def test_bounded_provider_shutdown_thread_is_daemon() -> None:
    """The background worker must be a daemon thread so it doesn't block process exit."""
    observed: list[bool] = []

    class _Recorder:
        def force_flush(self) -> None:
            observed.append(threading.current_thread().daemon)

        def shutdown(self) -> None:
            return

    bounded_provider_shutdown(_Recorder(), timeout_seconds=1.0)
    assert observed == [True]


def test_thread_is_named_for_operator_visibility() -> None:
    """Pin the worker thread name so it shows up identifiably in ps/py-spy/thread dumps.

    The exact string is part of the operator-debugging contract — when an
    abandoned shutdown thread leaks past process teardown, operators grep
    ``provide-provider-shutdown`` to identify it. Mutations to None/empty/
    uppercase/XX-prefix variants must be killed.
    """
    observed: list[str] = []

    class _Recorder:
        def force_flush(self) -> None:
            observed.append(threading.current_thread().name)

        def shutdown(self) -> None:
            return

    bounded_provider_shutdown(_Recorder(), timeout_seconds=1.0)
    assert observed == ["provide-provider-shutdown"]


def test_bounded_provider_shutdown_returns_quickly_when_completed_fast() -> None:
    """A fast provider must return promptly, not consume the full timeout."""
    provider = _RecordingProvider()
    started = time.monotonic()
    bounded_provider_shutdown(provider, timeout_seconds=30.0)
    assert time.monotonic() - started < 1.0
