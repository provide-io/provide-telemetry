# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting surviving mutation-testing mutants in resilience.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from undef.telemetry import health as health_mod
from undef.telemetry import resilience as resilience_mod
from undef.telemetry.resilience import (
    ExporterPolicy,
    _get_timeout_executor,
    _run_attempt_with_timeout,
    _warn_async_risk,
    get_exporter_policy,
    reset_resilience_for_tests,
    run_with_resilience,
    set_exporter_policy,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    health_mod.reset_health_for_tests()
    reset_resilience_for_tests()


# ---------------------------------------------------------------------------
# _warn_async_risk: exact signal name in warning message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warn_async_risk_message_contains_exact_signal_name_logs() -> None:
    """Kill mutants that change signal name strings in _warn_async_risk."""
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with pytest.warns(RuntimeWarning, match=r"resilience policy for logs uses retries/backoff"):
        _warn_async_risk("logs", policy)


@pytest.mark.asyncio
async def test_warn_async_risk_message_contains_exact_signal_name_traces() -> None:
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with pytest.warns(RuntimeWarning, match=r"resilience policy for traces uses retries/backoff"):
        _warn_async_risk("traces", policy)


@pytest.mark.asyncio
async def test_warn_async_risk_message_contains_exact_signal_name_metrics() -> None:
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with pytest.warns(RuntimeWarning, match=r"resilience policy for metrics uses retries/backoff"):
        _warn_async_risk("metrics", policy)


@pytest.mark.asyncio
async def test_warn_async_risk_allow_blocking_message_contains_signal() -> None:
    """Kill mutants in the allow_blocking_in_event_loop=True branch warning text."""
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=True)
    with pytest.warns(RuntimeWarning, match=r"resilience policy for traces allows blocking behavior"):
        _warn_async_risk("traces", policy)


@pytest.mark.asyncio
async def test_warn_async_risk_unknown_signal_falls_back_to_logs() -> None:
    """Kill the `in` -> `not in` mutant and the fallback 'logs' mutant."""
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with pytest.warns(RuntimeWarning, match=r"resilience policy for logs"):
        _warn_async_risk("unknown_signal", policy)


@pytest.mark.asyncio
async def test_warn_async_risk_adds_signal_to_warned_set() -> None:
    """Kill mutant: _async_warned_signals.add(None) instead of add(sig)."""
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with pytest.warns(RuntimeWarning):
        _warn_async_risk("traces", policy)
    # Second call for same signal should NOT warn (signal was added to set)
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        _warn_async_risk("traces", policy)
    assert len(w) == 0, "Expected no warning on second call for same signal"
    # But a different signal should still warn
    with pytest.warns(RuntimeWarning, match=r"resilience policy for metrics"):
        _warn_async_risk("metrics", policy)


@pytest.mark.asyncio
async def test_warn_async_risk_stacklevel_is_3() -> None:
    """Kill mutants changing stacklevel=3 to stacklevel=4 or removing it."""
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with patch("undef.telemetry.resilience.warnings.warn") as mock_warn:
        _warn_async_risk("logs", policy)
        mock_warn.assert_called_once()
        _, kwargs = mock_warn.call_args
        assert kwargs.get("stacklevel") == 3 or mock_warn.call_args[0][2] == 3


# ---------------------------------------------------------------------------
# reset_resilience_for_tests: all three signals reset, shutdown(wait=False)
# ---------------------------------------------------------------------------


def test_reset_resilience_resets_all_three_signals() -> None:
    """Kill mutants that change signal name strings in reset_resilience_for_tests."""
    custom = ExporterPolicy(retries=5, backoff_seconds=1.0, timeout_seconds=30.0)
    for signal in ("logs", "traces", "metrics"):
        set_exporter_policy(signal, custom)

    # Verify non-default policies are set
    for signal in ("logs", "traces", "metrics"):
        assert get_exporter_policy(signal).retries == 5

    reset_resilience_for_tests()

    # All three must be back to defaults
    for signal in ("logs", "traces", "metrics"):
        p = get_exporter_policy(signal)
        assert p.retries == 0, f"{signal} retries not reset"
        assert p.backoff_seconds == 0.0, f"{signal} backoff not reset"
        assert p.timeout_seconds == 10.0, f"{signal} timeout not reset"
        assert p.fail_open is True, f"{signal} fail_open not reset"


def test_reset_resilience_policies_are_exporterpolicy_not_none() -> None:
    """Kill mutant: _policies[signal] = None instead of ExporterPolicy()."""
    custom = ExporterPolicy(retries=3)
    for signal in ("logs", "traces", "metrics"):
        set_exporter_policy(signal, custom)

    reset_resilience_for_tests()

    for signal in ("logs", "traces", "metrics"):
        p = get_exporter_policy(signal)
        assert isinstance(p, ExporterPolicy), f"{signal} policy is not ExporterPolicy"


def test_reset_resilience_shuts_down_executor_with_wait_false() -> None:
    """Kill mutant: shutdown(wait=True) or shutdown(wait=None)."""
    # Force executor creation
    _get_timeout_executor()

    with patch.object(resilience_mod, "_timeout_executor") as mock_exec:
        mock_exec.shutdown = MagicMock()
        mock_exec.__bool__ = lambda self: True
        # We need to use the actual module attribute
        pass

    # Instead, test via the actual path: create executor, then reset
    executor = _get_timeout_executor()
    with patch.object(executor, "shutdown", wraps=executor.shutdown) as mock_shutdown:
        # Store reference so reset finds it
        resilience_mod._timeout_executor = executor
        reset_resilience_for_tests()
        mock_shutdown.assert_called_once_with(wait=False)


# ---------------------------------------------------------------------------
# _get_timeout_executor: max_workers=4
# ---------------------------------------------------------------------------


def test_get_timeout_executor_has_4_workers() -> None:
    """Kill mutant: max_workers=None or max_workers=5."""
    reset_resilience_for_tests()
    executor = _get_timeout_executor()
    assert executor._max_workers == 4


# ---------------------------------------------------------------------------
# _run_attempt_with_timeout: timeout_seconds=0 boundary (<=0 vs <0)
# ---------------------------------------------------------------------------


def test_run_attempt_with_timeout_zero_runs_directly() -> None:
    """Kill boundary mutant: timeout_seconds <= 0 vs < 0.

    When timeout_seconds is exactly 0, the operation should run directly
    without using the thread pool executor.
    """
    calls = {"direct": 0}

    def _op() -> str:
        calls["direct"] += 1
        return "direct"

    # With timeout=0, should run directly (no executor)
    with patch.object(resilience_mod, "_get_timeout_executor") as mock_get:
        result = _run_attempt_with_timeout(_op, 0.0)
        mock_get.assert_not_called()
    assert result == "direct"
    assert calls["direct"] == 1


def test_run_attempt_with_timeout_negative_runs_directly() -> None:
    """Negative timeout also runs directly."""
    with patch.object(resilience_mod, "_get_timeout_executor") as mock_get:
        result = _run_attempt_with_timeout(lambda: "neg", -1.0)
        mock_get.assert_not_called()
    assert result == "neg"


def test_run_attempt_with_timeout_positive_uses_executor() -> None:
    """Positive timeout uses the thread pool executor."""
    result = _run_attempt_with_timeout(lambda: "pooled", 5.0)
    assert result == "pooled"


# ---------------------------------------------------------------------------
# run_with_resilience: max(1, retries+1) vs max(2, ...)
# ---------------------------------------------------------------------------


def test_run_with_resilience_retries_zero_runs_exactly_once() -> None:
    """Kill mutant: max(2, policy.retries + 1) instead of max(1, ...).

    With retries=0, attempts = max(1, 0+1) = 1. If mutated to max(2, ...),
    it would run 2 times.
    """
    set_exporter_policy("logs", ExporterPolicy(retries=0, fail_open=True))
    calls = {"count": 0}

    def _op() -> str:
        calls["count"] += 1
        raise RuntimeError("fail")

    result = run_with_resilience("logs", _op)
    assert result is None
    assert calls["count"] == 1, "With retries=0, operation must run exactly once"


def test_run_with_resilience_retries_one_runs_twice() -> None:
    """Confirm retries=1 gives exactly 2 attempts."""
    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.0, fail_open=True))
    calls = {"count": 0}

    def _op() -> str:
        calls["count"] += 1
        raise RuntimeError("fail")

    result = run_with_resilience("logs", _op)
    assert result is None
    assert calls["count"] == 2


# ---------------------------------------------------------------------------
# run_with_resilience: success records latency
# ---------------------------------------------------------------------------


def test_run_with_resilience_success_records_latency() -> None:
    """Ensure successful operation records export success with latency."""
    set_exporter_policy("metrics", ExporterPolicy(retries=0))
    result = run_with_resilience("metrics", lambda: 42)
    assert result == 42
    snap = health_mod.get_health_snapshot()
    assert snap.export_latency_ms_metrics >= 0.0
