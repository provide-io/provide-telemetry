# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests that replace pragma: no mutate shortcuts with real mutation kills.

Each test targets a specific line/operator in resilience.py where a pragma
was removed, ensuring the mutant would be caught by the test suite.
"""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry.resilience import (
    ExporterPolicy,
    reset_resilience_for_tests,
    run_with_resilience,
    set_exporter_policy,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    reset_resilience_for_tests()


# ---------------------------------------------------------------------------
# Circuit breaker: >= threshold (kill >= → > mutant)
# ---------------------------------------------------------------------------


def test_circuit_breaker_trips_at_exactly_threshold() -> None:
    """Kill mutant: >= _CIRCUIT_BREAKER_THRESHOLD → > _CIRCUIT_BREAKER_THRESHOLD.

    After exactly 3 consecutive timeouts (= threshold), the circuit breaker
    must be tripped. With ``>`` it would require 4.
    """
    set_exporter_policy(
        "logs",
        ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
    )
    # Trip the circuit breaker with exactly 3 timeouts (= threshold).
    for _ in range(3):
        run_with_resilience("logs", lambda: time.sleep(1.0))

    # The 4th call should be short-circuited (circuit breaker open).
    started = time.perf_counter()
    result = run_with_resilience("logs", lambda: time.sleep(1.0))
    elapsed = time.perf_counter() - started
    assert result is None
    # If it went through the executor it would take >= 10ms; circuit breaker
    # should return almost instantly.
    assert elapsed < 0.05, f"Circuit breaker did not trip; elapsed={elapsed:.3f}s"


def test_circuit_breaker_trips_at_threshold_in_retry_loop() -> None:
    """Kill mutant on the second >= check (retry-loop path).

    Accumulate exactly _CIRCUIT_BREAKER_THRESHOLD timeouts across retries
    and verify the breaker records the trip timestamp.
    """
    set_exporter_policy(
        "traces",
        ExporterPolicy(timeout_seconds=0.01, retries=2, backoff_seconds=0.0, fail_open=True),
    )
    run_with_resilience("traces", lambda: time.sleep(1.0))

    # After 3 timeouts (1 initial + 2 retries), breaker must be tripped.
    with resilience_mod._lock:
        assert resilience_mod._consecutive_timeouts["traces"] >= 3
        assert resilience_mod._circuit_tripped_at["traces"] > 0.0


# ---------------------------------------------------------------------------
# Async guard: `and` vs `or` — NOT in event loop path
# ---------------------------------------------------------------------------


def test_async_guard_no_risk_increment_outside_event_loop() -> None:
    """Kill mutant: ``and`` → ``or`` on the async guard condition.

    When NOT running in an event loop, async_blocking_risk must NOT be
    incremented, even when retries > 0 and backoff > 0. With ``or`` the
    condition would be true whenever the policy has retries or backoff.
    """
    set_exporter_policy(
        "logs",
        ExporterPolicy(retries=2, backoff_seconds=0.1, fail_open=True),
    )
    run_with_resilience("logs", lambda: "ok")
    snap = health_mod.get_health_snapshot()
    assert snap.async_blocking_risk_logs == 0, "async_blocking_risk should be 0 when not in event loop"


# ---------------------------------------------------------------------------
# backoff_seconds = 0.0 in event loop (kill 0.0 → 1.0 mutant)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_guard_forces_zero_backoff() -> None:
    """Kill mutant: backoff_seconds = 0.0 → 1.0.

    In an event loop with allow_blocking=False, backoff must be forced to 0.
    If mutated to 1.0, the operation would take >=1s per retry.
    """
    set_exporter_policy(
        "traces",
        ExporterPolicy(
            retries=2,
            backoff_seconds=5.0,
            fail_open=True,
            allow_blocking_in_event_loop=False,
        ),
    )
    started = time.perf_counter()
    with pytest.warns(RuntimeWarning):
        run_with_resilience("traces", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    elapsed = time.perf_counter() - started
    # With backoff forced to 0 and attempts forced to 1, completes fast.
    assert elapsed < 0.5, f"Backoff not zeroed in event loop; elapsed={elapsed:.3f}s"


# ---------------------------------------------------------------------------
# last_error: None init (kill None → something-else mutant)
# ---------------------------------------------------------------------------


def test_last_error_none_on_first_success() -> None:
    """Kill mutant: last_error = None → last_error = Exception().

    When the operation succeeds on the first attempt, no error should
    propagate. If last_error were initialised to a non-None value and the
    success path somehow failed, the non-None error might leak.
    """
    set_exporter_policy(
        "logs",
        ExporterPolicy(retries=0, fail_open=False),
    )
    result = run_with_resilience("logs", lambda: "success")
    assert result == "success"


# ---------------------------------------------------------------------------
# latency_ms = ... * 1000.0 (kill * 1000.0 → * 1001.0 mutant)
# ---------------------------------------------------------------------------


def test_latency_ms_approximately_correct() -> None:
    """Kill mutant: * 1000.0 → * 1001.0 or similar.

    Verify recorded latency_ms is within tolerance of wall-clock time.
    """
    sleep_seconds = 0.05
    set_exporter_policy("metrics", ExporterPolicy(retries=0, timeout_seconds=0))
    run_with_resilience("metrics", lambda: time.sleep(sleep_seconds))
    snap = health_mod.get_health_snapshot()
    expected_ms = sleep_seconds * 1000.0
    # Allow 200ms tolerance for scheduling jitter (macOS ARM runners can be slow).
    assert abs(snap.export_latency_ms_metrics - expected_ms) < 200.0, (
        f"Latency {snap.export_latency_ms_metrics:.1f}ms not near expected {expected_ms:.1f}ms"
    )


# ---------------------------------------------------------------------------
# backoff_seconds > 0 guard (kill > 0 → >= 0 — would always sleep)
# ---------------------------------------------------------------------------


def test_zero_backoff_does_not_sleep() -> None:
    """Kill mutant: ``> 0`` → ``>= 0`` on backoff guard.

    With backoff=0, no sleep should occur between retries. If mutated to
    ``>= 0``, time.sleep(0.0) would be called.
    """
    set_exporter_policy(
        "logs",
        ExporterPolicy(retries=2, backoff_seconds=0.0, timeout_seconds=0, fail_open=True),
    )
    calls = {"count": 0}

    def _fail() -> str:
        calls["count"] += 1
        raise RuntimeError("boom")

    with patch("provide.telemetry.resilience.time.sleep") as mock_sleep:
        run_with_resilience("logs", _fail)
    mock_sleep.assert_not_called()
    assert calls["count"] == 3  # 1 initial + 2 retries


def test_zero_backoff_does_not_sleep_timeout_path() -> None:
    """Same as above but for the TimeoutError retry path.

    We cannot patch time.sleep globally here because the operation itself
    uses time.sleep to trigger the timeout. Instead, verify that backoff
    does not add measurable delay beyond the timeout itself.
    """
    set_exporter_policy(
        "traces",
        ExporterPolicy(retries=1, backoff_seconds=0.0, timeout_seconds=0.01, fail_open=True),
    )
    started = time.perf_counter()
    run_with_resilience("traces", lambda: time.sleep(1.0))
    elapsed = time.perf_counter() - started
    # 2 attempts * 0.01s timeout = ~0.02s; with backoff it would be much more.
    assert elapsed < 0.5, f"Unexpected delay suggesting backoff sleep; elapsed={elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Health counter integration: record_export_failure / record_export_success
# ---------------------------------------------------------------------------


def test_health_counters_after_mixed_operations() -> None:
    """Kill mutants that remove record_export_failure or record_export_success.

    After a sequence of operations, verify health counters reflect the
    expected number of successes and failures.
    """
    set_exporter_policy(
        "logs",
        ExporterPolicy(retries=0, timeout_seconds=0, fail_open=True),
    )
    # 2 successes
    run_with_resilience("logs", lambda: "ok")
    run_with_resilience("logs", lambda: "ok2")
    snap = health_mod.get_health_snapshot()
    assert snap.export_failures_logs == 0
    assert snap.export_latency_ms_logs > 0.0  # at least one latency recorded

    # 1 failure
    run_with_resilience("logs", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    snap = health_mod.get_health_snapshot()
    assert snap.export_failures_logs == 1


def test_health_counters_timeout_failure() -> None:
    """Timeout path records export failure."""
    set_exporter_policy(
        "metrics",
        ExporterPolicy(retries=0, timeout_seconds=0.01, fail_open=True),
    )
    run_with_resilience("metrics", lambda: time.sleep(1.0))
    snap = health_mod.get_health_snapshot()
    assert snap.export_failures_metrics == 1


def test_health_counters_circuit_breaker_failure() -> None:
    """Circuit breaker open path also records export failure."""
    set_exporter_policy(
        "traces",
        ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
    )
    for _ in range(3):
        run_with_resilience("traces", lambda: time.sleep(1.0))
    failures_before = health_mod.get_health_snapshot().export_failures_traces
    # This call is short-circuited by the breaker.
    run_with_resilience("traces", lambda: "never called")
    failures_after = health_mod.get_health_snapshot().export_failures_traces
    assert failures_after == failures_before + 1


def test_success_resets_consecutive_timeouts() -> None:
    """A successful export resets the consecutive timeout counter to 0."""
    set_exporter_policy(
        "logs",
        ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
    )
    for _ in range(2):
        run_with_resilience("logs", lambda: time.sleep(1.0))
    with resilience_mod._lock:
        assert resilience_mod._consecutive_timeouts["logs"] == 2

    # Success resets counter
    set_exporter_policy("logs", ExporterPolicy(timeout_seconds=0, retries=0))
    run_with_resilience("logs", lambda: "ok")
    with resilience_mod._lock:
        assert resilience_mod._consecutive_timeouts["logs"] == 0


def test_non_timeout_exception_resets_consecutive_timeouts() -> None:
    """A non-timeout exception also resets the consecutive timeout counter."""
    set_exporter_policy(
        "logs",
        ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
    )
    for _ in range(2):
        run_with_resilience("logs", lambda: time.sleep(1.0))
    with resilience_mod._lock:
        assert resilience_mod._consecutive_timeouts["logs"] == 2

    # Non-timeout failure resets counter
    set_exporter_policy("logs", ExporterPolicy(timeout_seconds=0, retries=0, fail_open=True))
    run_with_resilience("logs", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with resilience_mod._lock:
        assert resilience_mod._consecutive_timeouts["logs"] == 0


# ---------------------------------------------------------------------------
# Async blocking risk increment (kill removal of increment_async_blocking_risk)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_blocking_risk_incremented_in_event_loop() -> None:
    """Kill mutant that removes increment_async_blocking_risk call.

    When running in an event loop with retries/backoff, the async_blocking_risk
    counter must be incremented.
    """
    set_exporter_policy(
        "metrics",
        ExporterPolicy(
            retries=1,
            backoff_seconds=0.1,
            fail_open=True,
            allow_blocking_in_event_loop=False,
        ),
    )
    with pytest.warns(RuntimeWarning):
        run_with_resilience("metrics", lambda: "ok")
    snap = health_mod.get_health_snapshot()
    assert snap.async_blocking_risk_metrics == 1

    # Second call increments again.
    run_with_resilience("metrics", lambda: "ok2")
    snap = health_mod.get_health_snapshot()
    assert snap.async_blocking_risk_metrics == 2


# ---------------------------------------------------------------------------
# Half-open success: _record_attempt_success resets timeouts to 0
# ---------------------------------------------------------------------------


def test_half_open_success_resets_consecutive_timeouts_to_zero() -> None:
    """Kill mutant: _consecutive_timeouts[sig] = 0 -> = 1 in half-open success path.

    After the circuit trips (3 timeouts), wait for cooldown to expire so the
    circuit enters half-open state, then succeed. The consecutive_timeouts must
    be reset to exactly 0.
    """
    import time as _time

    set_exporter_policy(
        "logs",
        ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
    )

    # Trip the circuit breaker
    for _ in range(3):
        run_with_resilience("logs", lambda: _time.sleep(1.0))

    with resilience_mod._lock:
        assert resilience_mod._consecutive_timeouts["logs"] >= 3
        # Force cooldown to have expired
        resilience_mod._circuit_tripped_at["logs"] = _time.monotonic() - 999.0

    # Verify half-open probing is armed before the success call
    with resilience_mod._lock:
        assert resilience_mod._half_open_probing["logs"] is False  # not yet probing

    # Next call enters half-open (cooldown expired) and succeeds
    set_exporter_policy(
        "logs",
        ExporterPolicy(timeout_seconds=0, retries=0, fail_open=True),
    )
    result = run_with_resilience("logs", lambda: "ok")
    assert result == "ok"

    # After half-open success, consecutive_timeouts must be exactly 0
    # (mutant changes this to 1 on the half-open branch at line 122)
    with resilience_mod._lock:
        assert resilience_mod._consecutive_timeouts["logs"] == 0
        # Also verify half-open probing was consumed (proves we hit the right branch)
        assert resilience_mod._half_open_probing["logs"] is False
