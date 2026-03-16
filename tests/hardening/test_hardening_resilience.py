# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Hardening integration tests for resilience async guard paths.

Split from test_hardening_features.py to stay under the 500 LOC limit.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any

import pytest

from undef.telemetry import backpressure as backpressure_mod
from undef.telemetry import cardinality as cardinality_mod
from undef.telemetry import health as health_mod
from undef.telemetry import pii as pii_mod
from undef.telemetry import resilience as resilience_mod
from undef.telemetry import sampling as sampling_mod
from undef.telemetry.logger.context import clear_context
from undef.telemetry.tracing.context import set_trace_context


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
    resilience_mod.set_exporter_policy(
        "metrics",
        resilience_mod.ExporterPolicy(retries=1, timeout_seconds=0.01, backoff_seconds=0.0, fail_open=True),
    )
    calls = {"count": 0}

    def _too_slow() -> str:
        calls["count"] += 1
        time.sleep(0.05)
        return "late"

    assert resilience_mod.run_with_resilience("metrics", _too_slow) is None
    assert calls["count"] == 2
    assert health_mod.get_health_snapshot().export_failures_metrics == 2
    assert health_mod.get_health_snapshot().retries_metrics == 1

    resilience_mod.set_exporter_policy(
        "logs",
        resilience_mod.ExporterPolicy(retries=0, timeout_seconds=0.01, fail_open=False),
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
