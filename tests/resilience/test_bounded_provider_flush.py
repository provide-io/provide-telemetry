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


def _hanging_provider(release: threading.Event, wait: float = 5.0) -> object:
    """A provider whose force_flush blocks until *release* is set.

    The wait ceiling is a backstop so a failing test cannot wedge the worker
    forever; every caller is expected to set *release* in its own teardown.
    Kept short on purpose — a wedged worker holds a slot in the process-wide
    _abandoned_workers budget for the whole ceiling, and a later test asserting
    the budget is clear would fail for an unrelated reason.
    """

    class _Hanging:
        def force_flush(self) -> None:
            release.wait(wait)

    return _Hanging()


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
    try:
        with pytest.warns(RuntimeWarning, match="flush exceeded .* deadline"):
            assert bounded_provider_flush(_hanging_provider(release), timeout_seconds=0.05) is False
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


def test_a_drain_that_finishes_in_time_never_touches_the_budget() -> None:
    """Only workers abandoned at their deadline may consume budget.

    Counting in-flight workers instead would make healthy concurrent drains —
    an ASGI app flushing per request against a collector that takes 200ms —
    decline each other and report a failure that never happened.
    """
    from provide.telemetry import _provider_drain

    _provider_drain._reset_abandoned_workers_for_tests()

    for _ in range(_provider_drain._MAX_ABANDONED_WORKERS + 4):
        assert bounded_provider_flush(_RecordingProvider(), timeout_seconds=1.0) is True
        assert _provider_drain._abandoned_workers == 0


def test_concurrent_healthy_drains_are_all_attempted() -> None:
    """More simultaneous slow-but-fine drains than the budget: none may be declined."""
    from provide.telemetry import _provider_drain

    _provider_drain._reset_abandoned_workers_for_tests()

    attempts = _provider_drain._MAX_ABANDONED_WORKERS + 4
    # list.append is atomic under the GIL, so no lock is needed for either tally.
    flushed: list[str] = []
    results: list[bool] = []

    class _Slow:
        def force_flush(self) -> None:
            flushed.append("force_flush")
            time.sleep(0.05)

    def _drain() -> None:
        results.append(bounded_provider_flush(_Slow(), timeout_seconds=5.0))

    callers = [threading.Thread(target=_drain) for _ in range(attempts)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(10.0)

    assert results == [True] * attempts
    # Every provider was really flushed — none was declined with a bare False.
    assert len(flushed) == attempts


def test_an_abandoned_worker_gives_its_slot_back_when_it_finally_finishes() -> None:
    """The slot is held for exactly as long as the worker is stuck, and no longer."""
    from provide.telemetry import _provider_drain

    _provider_drain._reset_abandoned_workers_for_tests()
    release = threading.Event()

    with pytest.warns(RuntimeWarning, match="flush exceeded"):
        assert bounded_provider_flush(_hanging_provider(release, wait=10.0), timeout_seconds=0.01) is False
    assert _provider_drain._abandoned_workers == 1

    release.set()
    deadline = time.monotonic() + 5.0
    while _provider_drain._abandoned_workers != 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _provider_drain._abandoned_workers == 0


def test_reports_an_incomplete_flush_as_failure() -> None:
    """OTel's force_flush returns False when it gave up with records still queued.

    Discarding that would tell a caller flushing before a serverless freeze that
    its spans are out when they were dropped — and would disagree with Rust,
    where the same drain returns false.
    """

    class _Incomplete:
        def force_flush(self) -> bool:
            return False

    with pytest.warns(RuntimeWarning, match="incomplete drain from force_flush"):
        assert bounded_provider_flush(_Incomplete(), timeout_seconds=1.0) is False


def test_a_truthy_non_boolean_force_flush_return_is_success() -> None:
    """Only an explicit False means failure — a provider returning None is fine."""

    class _ReturnsNone:
        def force_flush(self) -> None:
            return None

    assert bounded_provider_flush(_ReturnsNone(), timeout_seconds=1.0) is True


def test_a_worker_that_finishes_in_the_deadline_race_does_not_consume_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wait can time out in the same instant the worker finishes.

    Only one of the two may account for the slot: incrementing here after the
    worker has already run its decrement-if-counted would strand a slot that no
    thread is holding, and eight of those retire the budget for good.

    Deliberately pinned to the current lock schedule — it fires on the first
    main-thread acquire taken once a worker thread exists, and identifies that
    worker by the operator-facing thread name. If _bounded_provider_call gains
    another _abandoned_lock acquire, moves the accounting behind a helper, or
    renames the worker, rewrite this test rather than patching it: the invariant
    worth keeping is "exactly one side charges the slot", not this interleaving.
    """
    from provide.telemetry import _provider_drain

    _provider_drain._reset_abandoned_workers_for_tests()

    release = threading.Event()
    main_thread = threading.current_thread()
    real_lock = _provider_drain._abandoned_lock
    tripped = threading.Event()

    class _RacingLock:
        """Let the worker run to completion inside the post-deadline acquire."""

        def __enter__(self) -> None:
            if threading.current_thread() is main_thread and not tripped.is_set():
                workers = [t for t in threading.enumerate() if t.name == "provide-provider-flush"]
                if workers:
                    tripped.set()
                    release.set()
                    for worker in workers:
                        worker.join(5.0)
            real_lock.acquire()

        def __exit__(self, *_exc: object) -> None:
            real_lock.release()

    monkeypatch.setattr(_provider_drain, "_abandoned_lock", _RacingLock())

    try:
        with pytest.warns(RuntimeWarning, match="flush exceeded"):
            assert bounded_provider_flush(_hanging_provider(release), timeout_seconds=0.01) is False
    finally:
        # _RacingLock releases the worker only when the race trips; if it did
        # not, the worker would sit on a budget slot until its wait ceiling and
        # fail an unrelated later test.
        release.set()

    assert tripped.is_set(), "the race was never exercised"
    assert _provider_drain._abandoned_workers == 0


def test_reports_failure_without_consuming_budget_when_no_thread_can_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "can't start new thread" is the exhaustion the cap exists for — it must not
    also retire a slot permanently, nor raise out of a bool-returning drain."""
    from provide.telemetry import _provider_drain

    _provider_drain._reset_abandoned_workers_for_tests()

    def _refuse(self: threading.Thread) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", _refuse)

    with pytest.warns(RuntimeWarning, match="could not start a drain worker"):
        assert bounded_provider_flush(_RecordingProvider(), timeout_seconds=1.0) is False
    assert _provider_drain._abandoned_workers == 0
