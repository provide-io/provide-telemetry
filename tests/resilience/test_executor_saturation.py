# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
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
import types
from collections.abc import Callable, Iterator

import pytest

from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry.resilience import ExporterPolicy, run_with_resilience

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
        assert threading.active_count() <= baseline


class TestCircuitBreakerLifecycle:
    def test_full_lifecycle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Trip → block → half-open success → reset → re-trip → half-open failure."""
        event = threading.Event()
        _tight_policy("logs")

        # ── 1. Trip ──────────────────────────────────────────────────────────
        _trip_circuit("logs", event)
        assert resilience_mod._consecutive_timeouts["logs"] == resilience_mod._CIRCUIT_BREAKER_THRESHOLD

        # ── 2. Block ─────────────────────────────────────────────────────────
        not_called: list[bool] = []

        def _sentinel() -> str:
            not_called.append(True)
            return "oops"

        result = run_with_resilience("logs", _sentinel)
        assert result is None  # circuit open → fail_open → None
        assert not_called == []  # sentinel never ran
        snap = health_mod.get_health_snapshot()
        # Failures = 3 timeouts + 1 circuit-open rejection
        assert snap.export_failures_logs == resilience_mod._CIRCUIT_BREAKER_THRESHOLD + 1

        # ── 3. Advance clock past cooldown ───────────────────────────────────
        tripped_at = resilience_mod._circuit_tripped_at["logs"]
        oc1 = resilience_mod._open_count["logs"]
        cooldown1 = min(
            resilience_mod._CIRCUIT_BASE_COOLDOWN * (2**oc1),
            resilience_mod._CIRCUIT_MAX_COOLDOWN,
        )
        fake_time = types.SimpleNamespace(
            monotonic=lambda: tripped_at + cooldown1 + 1.0,
            perf_counter=time.perf_counter,
            sleep=time.sleep,
        )
        monkeypatch.setattr(resilience_mod, "time", fake_time)

        # ── 4. Half-open probe — success ─────────────────────────────────────
        # Release the stuck event so the probe completes within timeout.
        event.set()
        probe_result = run_with_resilience("logs", lambda: "probe-ok")
        assert probe_result == "probe-ok"
        assert resilience_mod._consecutive_timeouts["logs"] == 0  # reset on success

        # ── 5. Re-trip ───────────────────────────────────────────────────────
        # future.result(timeout=...) raises TimeoutError whether the task is
        # queued or running, so this is correct even if the executor workers are
        # still occupied by the previous batch's draining threads.
        event.clear()
        # Restore real time so timeouts fire normally.
        monkeypatch.setattr(resilience_mod, "time", time)
        _trip_circuit("logs", event)
        assert resilience_mod._consecutive_timeouts["logs"] == resilience_mod._CIRCUIT_BREAKER_THRESHOLD

        # ── 6. Half-open probe — failure ─────────────────────────────────────
        tripped_at2 = resilience_mod._circuit_tripped_at["logs"]
        oc2 = resilience_mod._open_count["logs"]
        cooldown2 = min(
            resilience_mod._CIRCUIT_BASE_COOLDOWN * (2**oc2),
            resilience_mod._CIRCUIT_MAX_COOLDOWN,
        )
        fake_time2 = types.SimpleNamespace(
            monotonic=lambda: tripped_at2 + cooldown2 + 1.0,
            perf_counter=time.perf_counter,
            sleep=time.sleep,
        )
        monkeypatch.setattr(resilience_mod, "time", fake_time2)

        # Probe times out (event still closed) → circuit re-trips.
        result2 = run_with_resilience("logs", _make_stuck_op(event))
        assert result2 is None
        assert resilience_mod._consecutive_timeouts["logs"] >= resilience_mod._CIRCUIT_BREAKER_THRESHOLD

        # Cleanup
        event.set()


class TestCrossSignalIsolation:
    def test_logs_storm_does_not_starve_traces_or_metrics(self) -> None:
        """A timeout storm on logs leaves traces and metrics unaffected."""
        logs_event = threading.Event()  # held closed — logs ops will time out
        _tight_policy("logs")
        # Use a generous timeout for traces/metrics so they succeed comfortably.
        resilience_mod.set_exporter_policy(
            "traces",
            ExporterPolicy(retries=0, timeout_seconds=1.0, fail_open=True),
        )
        resilience_mod.set_exporter_policy(
            "metrics",
            ExporterPolicy(retries=0, timeout_seconds=1.0, fail_open=True),
        )

        # Trip the logs circuit — 2 workers now hold stuck threads.
        _trip_circuit("logs", logs_event)

        # While logs workers are occupied, traces and metrics must still work.
        traces_result = run_with_resilience("traces", lambda: "traces-ok")
        metrics_result = run_with_resilience("metrics", lambda: "metrics-ok")

        assert traces_result == "traces-ok"
        assert metrics_result == "metrics-ok"

        # Health counters: only logs has failures.
        snap = health_mod.get_health_snapshot()
        assert snap.export_failures_traces == 0
        assert snap.export_failures_metrics == 0
        assert snap.export_failures_logs == resilience_mod._CIRCUIT_BREAKER_THRESHOLD

        # Timeout counters: only logs is non-zero.
        assert resilience_mod._consecutive_timeouts["traces"] == 0
        assert resilience_mod._consecutive_timeouts["metrics"] == 0

        # Cleanup
        logs_event.set()


class TestExecutorSemaphore:
    def test_semaphore_full_returns_none(self) -> None:
        """When the semaphore is exhausted, run_with_resilience returns None (fail-open)."""
        resilience_mod.set_exporter_policy(
            "logs",
            ExporterPolicy(retries=0, timeout_seconds=0.1, fail_open=True),
        )
        sem = resilience_mod._get_executor_semaphore("logs")
        # Drain the semaphore completely so no new submissions are accepted.
        drained = 0
        while sem.acquire(blocking=False):
            drained += 1

        try:
            result = run_with_resilience("logs", lambda: "should-not-run")
            assert result is None
        finally:
            for _ in range(drained):
                sem.release()
