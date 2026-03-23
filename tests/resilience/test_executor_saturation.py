# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Executor saturation load tests for resilience.py.

Tests three failure modes under sustained export failures:
- Ghost thread accumulation: circuit breaker bounds thread growth.
- Circuit breaker lifecycle: trip → block → half-open → reset → re-trip.
- Cross-signal isolation: a logs timeout storm cannot starve traces/metrics workers.
"""

from __future__ import annotations

import threading
import time
import types  # noqa: F401 — used in Task 3 (TestCircuitBreakerLifecycle)
from collections.abc import Callable, Iterator

import pytest

from undef.telemetry import health as health_mod
from undef.telemetry import resilience as resilience_mod
from undef.telemetry.resilience import ExporterPolicy, run_with_resilience

pytestmark = pytest.mark.integration

_TIMEOUT_S = 0.005  # 5 ms — tight enough to reliably time out a blocked op


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    resilience_mod.reset_resilience_for_tests()
    health_mod.reset_health_for_tests()
    yield
    # Tests must release their own events before this runs.
    # reset_resilience_for_tests() shuts down executors (wait=False) and clears
    # _timeout_executors so the next test gets a fresh pool.
    try:
        resilience_mod.reset_resilience_for_tests()
    finally:
        health_mod.reset_health_for_tests()


def _make_stuck_op(event: threading.Event) -> Callable[[], str]:
    """Return an operation that blocks until *event* is set (5 s safety cap)."""

    def _op() -> str:
        event.wait(timeout=5.0)
        return "done"

    return _op


def _tight_policy(signal: str) -> None:
    """Set a tight-timeout, no-retry, fail-open policy for *signal*."""
    resilience_mod.set_exporter_policy(
        signal,
        ExporterPolicy(retries=0, timeout_seconds=_TIMEOUT_S, fail_open=True),
    )


def _trip_circuit(signal: str, event: threading.Event) -> None:
    """Submit exactly _CIRCUIT_BREAKER_THRESHOLD slow ops to trip the circuit."""
    threshold = resilience_mod._CIRCUIT_BREAKER_THRESHOLD
    for _ in range(threshold):
        result = run_with_resilience(signal, _make_stuck_op(event))
        assert result is None, f"Expected fail_open None for {signal!r}, got {result!r}"


class TestGhostThreadAccumulation:
    def test_circuit_breaker_bounds_ghost_threads(self) -> None:
        """Circuit breaker trips after threshold timeouts; no further threads accumulate."""
        event = threading.Event()  # held closed — ops will block and time out
        _tight_policy("logs")
        baseline = threading.active_count()

        # Trip the circuit (threshold = 3 consecutive timeouts)
        _trip_circuit("logs", event)

        # After tripping: at most 2 ghost threads (the 2 executor workers).
        # Further calls are rejected by the open circuit without submitting.
        assert threading.active_count() <= baseline + 2

        call_count = 0

        def _counting_op() -> str:
            nonlocal call_count
            call_count += 1
            return "should not run"

        # With circuit open, these must be rejected without calling the operation.
        for _ in range(5):
            result = run_with_resilience("logs", _counting_op)
            assert result is None

        assert call_count == 0  # operation never called
        assert threading.active_count() <= baseline + 2  # no new threads

        # Drain: release event so stuck threads can finish, then shut down executor.
        event.set()
        resilience_mod.reset_resilience_for_tests()
        health_mod.reset_health_for_tests()

        # executor.shutdown(wait=False) returns immediately; worker threads need a
        # moment to finish their event.wait() call and exit.  Poll rather than
        # assert immediately to avoid a race on loaded CI machines.
        deadline = time.monotonic() + 2.0
        while threading.active_count() > baseline and time.monotonic() < deadline:
            time.sleep(0.005)
        assert threading.active_count() == baseline
