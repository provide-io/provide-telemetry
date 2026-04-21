# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Hardening integration tests for resilience async guard paths.

Split from test_hardening_features.py to stay under the 500 LOC limit.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any

import pytest

from provide.telemetry import backpressure as backpressure_mod
from provide.telemetry import cardinality as cardinality_mod
from provide.telemetry import health as health_mod
from provide.telemetry import pii as pii_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry import sampling as sampling_mod
from provide.telemetry.logger.context import clear_context
from provide.telemetry.tracing.context import set_trace_context


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    health_mod.reset_health_for_tests()
    sampling_mod.reset_sampling_for_tests()
    backpressure_mod.reset_queues_for_tests()
    resilience_mod.reset_resilience_for_tests()
    cardinality_mod.clear_cardinality_limits()
    pii_mod.reset_pii_rules_for_tests()
    clear_context()
    set_trace_context(None, None)


def test_resilience_timeout_enforced_fail_open_and_fail_closed() -> None:
    # allow_blocking_in_event_loop=True ensures the timeout executor is always used.
    # Without it, pytest-asyncio auto mode can leave a running event loop in the
    # test worker, causing _is_running_in_event_loop() to return True, which sets
    # skip_executor=True and bypasses timeout enforcement entirely.
    resilience_mod.set_exporter_policy(
        "metrics",
        resilience_mod.ExporterPolicy(
            retries=1,
            timeout_seconds=0.01,
            backoff_seconds=0.0,
            fail_open=True,
            allow_blocking_in_event_loop=True,
        ),
    )
    calls = {"count": 0}

    def _too_slow() -> str:
        calls["count"] += 1
        time.sleep(0.3)  # 30x the timeout — reliable on loaded CI machines
        return "late"

    assert resilience_mod.run_with_resilience("metrics", _too_slow) is None
    assert calls["count"] == 2
    assert health_mod.get_health_snapshot().export_failures_metrics == 2
    assert health_mod.get_health_snapshot().retries_metrics == 1

    resilience_mod.set_exporter_policy(
        "logs",
        resilience_mod.ExporterPolicy(
            retries=0,
            timeout_seconds=0.01,
            fail_open=False,
            allow_blocking_in_event_loop=True,
        ),
    )
    with pytest.raises(TimeoutError, match="operation timed out"):
        resilience_mod.run_with_resilience("logs", _too_slow)


def test_run_attempt_with_timeout_zero_delegates_directly() -> None:
    assert resilience_mod._run_attempt_with_timeout("logs", lambda: "ok", 0.0) == "ok"


def test_run_attempt_with_timeout_cancel_path(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled = {"count": 0}

    class _FakeFuture:
        def result(self, timeout: float) -> object:
            _ = timeout
            raise concurrent.futures.TimeoutError()

        def cancel(self) -> bool:
            cancelled["count"] += 1
            return True

    class _FakeExecutor:
        def submit(self, fn: Any, *args: Any, **kwargs: Any) -> _FakeFuture:
            return _FakeFuture()

    monkeypatch.setattr(resilience_mod, "_get_timeout_executor", lambda _signal: _FakeExecutor())

    with pytest.raises(TimeoutError, match="operation timed out"):
        resilience_mod._run_attempt_with_timeout("logs", lambda: "ok", 0.1)
    assert cancelled["count"] == 1


def test_timeout_executor_singleton_per_signal() -> None:
    resilience_mod.reset_resilience_for_tests()
    ex1 = resilience_mod._get_timeout_executor("logs")
    ex2 = resilience_mod._get_timeout_executor("logs")
    assert ex1 is ex2
    # Different signals get different executors
    ex_traces = resilience_mod._get_timeout_executor("traces")
    assert ex_traces is not ex1
    # Reset clears all executors
    resilience_mod.reset_resilience_for_tests()
    ex3 = resilience_mod._get_timeout_executor("logs")
    assert ex3 is not ex1


@pytest.mark.asyncio
async def test_resilience_async_guard_forces_fail_fast_without_override() -> None:
    resilience_mod.set_exporter_policy(
        "logs",
        resilience_mod.ExporterPolicy(
            retries=2, backoff_seconds=0.5, fail_open=True, allow_blocking_in_event_loop=False
        ),
    )
    calls = {"count": 0}

    def _always_fail() -> str:
        calls["count"] += 1
        raise RuntimeError("boom")

    with pytest.warns(RuntimeWarning, match="forcing fail-fast behavior"):
        assert resilience_mod.run_with_resilience("logs", _always_fail) is None
    assert calls["count"] == 1
    assert health_mod.get_health_snapshot().async_blocking_risk_logs == 1


@pytest.mark.asyncio
async def test_resilience_async_guard_allows_blocking_when_explicit() -> None:
    resilience_mod.set_exporter_policy(
        "metrics",
        resilience_mod.ExporterPolicy(
            retries=1, backoff_seconds=0.0, fail_open=True, allow_blocking_in_event_loop=True
        ),
    )
    calls = {"count": 0}

    def _flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return "ok"

    with pytest.warns(RuntimeWarning, match="allows blocking behavior"):
        assert resilience_mod.run_with_resilience("metrics", _flaky) == "ok"
    assert calls["count"] == 2
    snap = health_mod.get_health_snapshot()
    assert snap.async_blocking_risk_metrics == 1
    assert snap.retries_metrics == 1


@pytest.mark.asyncio
async def test_resilience_async_guard_warns_only_once_per_signal() -> None:
    resilience_mod.set_exporter_policy(
        "traces",
        resilience_mod.ExporterPolicy(
            retries=1, backoff_seconds=0.0, fail_open=True, allow_blocking_in_event_loop=True
        ),
    )

    calls = {"count": 0}

    def _always_fail() -> str:
        calls["count"] += 1
        raise RuntimeError("boom")

    with pytest.warns(RuntimeWarning, match="allows blocking behavior"):
        assert resilience_mod.run_with_resilience("traces", _always_fail) is None
    # Warning is suppressed for same signal after first emission.
    assert resilience_mod.run_with_resilience("traces", _always_fail) is None
    assert calls["count"] == 4


def test_executor_replaced_after_circuit_breaker_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ghost thread defense: executor is replaced when circuit breaker trips.

    After consecutive timeouts hit the threshold, the old executor (with
    potentially hung threads) is abandoned and a fresh one is created for
    the next probe attempt.
    """
    resilience_mod.reset_resilience_for_tests()
    monkeypatch.setattr(resilience_mod, "_is_running_in_event_loop", lambda: False)
    resilience_mod.set_exporter_policy(
        "logs",
        resilience_mod.ExporterPolicy(timeout_seconds=0.01, retries=0, fail_open=True),
    )

    # Get the initial executor.
    executor_before = resilience_mod._get_timeout_executor("logs")

    # Trigger enough timeouts to trip the circuit breaker (threshold=3).
    for _ in range(3):
        resilience_mod.run_with_resilience("logs", lambda: time.sleep(1.0))

    # The old executor should have been replaced.
    executor_after = resilience_mod._get_timeout_executor("logs")
    assert executor_before is not executor_after


def test_maybe_replace_executor_no_op_when_no_executor() -> None:
    """_maybe_replace_executor is safe when no executor exists for the signal."""
    resilience_mod.reset_resilience_for_tests()
    # Force consecutive_timeouts above threshold without creating an executor.
    with resilience_mod._lock:
        resilience_mod._consecutive_timeouts["logs"] = 10
    # Should not raise even though no executor exists.
    resilience_mod._maybe_replace_executor("logs")
