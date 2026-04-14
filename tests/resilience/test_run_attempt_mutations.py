# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in _run_attempt_with_timeout (resilience.py).

Targets:
  mutmut_5: _get_executor_semaphore(signal) → _get_executor_semaphore(None)
  mutmut_7: sem.acquire(blocking=False) → sem.acquire(blocking=None)
  mutmut_8: sem.acquire(blocking=False) → sem.acquire(blocking=True)
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from provide.telemetry import resilience as resilience_mod
from provide.telemetry.resilience import (
    _get_executor_semaphore,
    _run_attempt_with_timeout,
    reset_resilience_for_tests,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_resilience_for_tests()


# ---------------------------------------------------------------------------
# mutmut_5: _get_executor_semaphore(signal) → _get_executor_semaphore(None)
#
# If None is passed as the signal key, all signals would share (or create a
# separate) semaphore under the None key. By exhausting the semaphore for
# one signal and checking that the other signal is unaffected, we confirm
# that per-signal semaphore isolation is working correctly. With the mutation,
# both signals would share the None semaphore so exhausting "logs" would
# also block "traces".
# ---------------------------------------------------------------------------


def test_per_signal_semaphore_isolation() -> None:
    """Kill mutmut_5: semaphore key must be the signal, not None.

    Exhausting the semaphore for 'logs' must not affect 'traces'.
    With the mutation (None key), both signals share the same semaphore,
    so draining 'logs' would also prevent 'traces' from acquiring.
    """
    logs_sem = _get_executor_semaphore("logs")
    traces_sem = _get_executor_semaphore("traces")

    # Verify the two semaphores are distinct objects.
    assert logs_sem is not traces_sem, (
        "Each signal must have its own semaphore; mutation _get_executor_semaphore(None) "
        "would return the same semaphore for all signals"
    )


def test_per_signal_semaphore_independent_counts() -> None:
    """Kill mutmut_5: draining 'logs' semaphore must not exhaust 'traces'.

    With the mutation, both signals share the None-keyed semaphore, so
    acquiring all permits from one would prevent the other from running.
    """
    logs_sem = _get_executor_semaphore("logs")
    traces_sem = _get_executor_semaphore("traces")

    # Drain the logs semaphore completely.
    max_pending = resilience_mod._EXECUTOR_MAX_PENDING
    acquired: list[bool] = []
    for _ in range(max_pending):
        acquired.append(logs_sem.acquire(blocking=False))

    try:
        # traces semaphore must still be acquirable (it's independent).
        assert traces_sem.acquire(blocking=False), (
            "traces semaphore must be unaffected by draining the logs semaphore; "
            "mutation uses None key so both share one semaphore"
        )
        traces_sem.release()
    finally:
        # Release all acquired permits.
        for ok in acquired:
            if ok:
                logs_sem.release()


# ---------------------------------------------------------------------------
# mutmut_7: sem.acquire(blocking=None) — treated as truthy → blocks forever
# mutmut_8: sem.acquire(blocking=True) — blocks until a permit is free
#
# The correct behaviour is blocking=False: if no permit is immediately
# available, return False and drop the operation (fail-open). With blocking=True
# or blocking=None, the call would hang when the semaphore is exhausted.
# We test this by exhausting the semaphore first, then confirming that
# _run_attempt_with_timeout returns None immediately (not blocking).
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_run_attempt_drops_when_semaphore_full_does_not_block() -> None:
    """Kill mutmut_7 (blocking=None) and mutmut_8 (blocking=True).

    When the per-signal semaphore is exhausted, _run_attempt_with_timeout
    must return None immediately (fail-open) rather than blocking.

    With blocking=True or blocking=None the call would hang forever when
    there are no free permits; we detect that by running in a thread with
    a short deadline.
    """
    sem = _get_executor_semaphore("logs")
    max_pending = resilience_mod._EXECUTOR_MAX_PENDING

    # Drain all permits from the semaphore.
    acquired: list[bool] = []
    for _ in range(max_pending):
        acquired.append(sem.acquire(blocking=False))

    result_holder: dict[str, Any] = {}
    exc_holder: dict[str, BaseException] = {}

    def _run() -> None:
        try:
            result_holder["value"] = _run_attempt_with_timeout("logs", lambda: "should_not_run", timeout_seconds=5.0)
        except BaseException as exc:
            exc_holder["exc"] = exc

    # Run in a thread with a tight deadline. If blocking=True the thread would
    # hang; with blocking=False it returns immediately.
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=2.0)

    # Release all acquired permits before assertions so cleanup is guaranteed.
    for ok in acquired:
        if ok:
            sem.release()

    assert not t.is_alive(), "Thread is still alive — sem.acquire is blocking (mutation blocking=True/None active)"
    # Saturation now raises ExecutorSaturated so the outer retry_loop honors
    # policy.fail_open (either returns None or re-raises) instead of silently
    # treating the drop as a successful attempt.
    assert isinstance(exc_holder.get("exc"), resilience_mod.ExecutorSaturated)
    assert "value" not in result_holder
