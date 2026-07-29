# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for :func:`provide.telemetry.resilience.bounded_provider_flush`.

The drain half of ``bounded_provider_shutdown``: same deadline machinery, but
the provider must survive the call — nothing may be shut down.
"""

from __future__ import annotations

import threading
import time

import pytest

from provide.telemetry._provider_drain import bounded_provider_flush


class _RecordingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def force_flush(self) -> None:
        self.calls.append("force_flush")

    def shutdown(self) -> None:  # pragma: no cover - must never be called
        self.calls.append("shutdown")


def test_flushes_without_shutting_the_provider_down() -> None:
    provider = _RecordingProvider()
    assert bounded_provider_flush(provider, timeout_seconds=1.0) is True
    assert provider.calls == ["force_flush"]


def test_returns_true_when_provider_has_no_force_flush() -> None:
    class _Empty:
        pass

    assert bounded_provider_flush(_Empty(), timeout_seconds=1.0) is True


def test_skips_a_non_callable_force_flush_attribute() -> None:
    class _NonCallable:
        force_flush = "not callable"

    assert bounded_provider_flush(_NonCallable(), timeout_seconds=1.0) is True


def test_propagates_exception_raised_by_force_flush() -> None:
    class _Boom:
        def force_flush(self) -> None:
            raise RuntimeError("flush boom")

    with pytest.raises(RuntimeError, match="flush boom"):
        bounded_provider_flush(_Boom(), timeout_seconds=1.0)


def test_abandons_and_warns_on_timeout() -> None:
    release = threading.Event()

    class _Hanging:
        def force_flush(self) -> None:
            release.wait(5.0)

    try:
        with pytest.warns(RuntimeWarning, match="flush exceeded .* deadline"):
            assert bounded_provider_flush(_Hanging(), timeout_seconds=0.05) is False
    finally:
        # Let the abandoned daemon thread exit cleanly.
        release.set()
        time.sleep(0.05)


def test_flush_thread_is_daemon() -> None:
    """The worker must be a daemon thread so an abandoned flush cannot block exit."""
    observed: list[bool] = []

    class _Recorder:
        def force_flush(self) -> None:
            observed.append(threading.current_thread().daemon)

    bounded_provider_flush(_Recorder(), timeout_seconds=1.0)
    assert observed == [True]


def test_flush_thread_is_named_for_operator_visibility() -> None:
    """Pin the worker thread name — operators grep it in ps/py-spy/thread dumps.

    Distinct from the shutdown worker's name so an abandoned thread says which
    call leaked it. Mutations to None/empty/uppercase/XX-prefix must be killed.
    """
    observed: list[str] = []

    class _Recorder:
        def force_flush(self) -> None:
            observed.append(threading.current_thread().name)

    bounded_provider_flush(_Recorder(), timeout_seconds=1.0)
    assert observed == ["provide-provider-flush"]


def test_worker_budget_returns_to_zero_after_drains_finish() -> None:
    """The budget must be given back, exactly once, by every worker that finishes.

    Leaking a slot per drain would silently retire the budget after eight calls;
    giving back too many would let unbounded workers accumulate again.
    """
    import time

    from provide.telemetry import _provider_drain

    _provider_drain._reset_pending_workers_for_tests()
    assert _provider_drain._pending_workers == 0

    for _ in range(3):
        assert bounded_provider_flush(_RecordingProvider(), timeout_seconds=1.0) is True

    # The decrement lands in the worker's finally, just after the wait returns.
    deadline = time.monotonic() + 2.0
    while _provider_drain._pending_workers != 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _provider_drain._pending_workers == 0
