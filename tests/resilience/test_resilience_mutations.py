# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting surviving mutation-testing mutants in resilience.py."""

from __future__ import annotations

import warnings
from unittest.mock import patch

import pytest

from provide.telemetry import health as health_mod
from provide.telemetry import resilience as resilience_mod
from provide.telemetry.resilience import (
    ExporterPolicy,
    _get_timeout_executor,
    _is_running_in_event_loop,
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
async def test_warn_async_risk_uses_signal_name_in_warning() -> None:
    """Warn message includes the actual signal name (no remapping to 'logs')."""
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with pytest.warns(RuntimeWarning, match=r"resilience policy for unknown_signal"):
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
async def test_warn_async_risk_policy_change_triggers_new_warning() -> None:
    """Kill mutant: key is just signal (not tuple) so policy change doesn't warn again."""
    policy_block = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=True)
    policy_fail = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with pytest.warns(RuntimeWarning, match="allows blocking"):
        _warn_async_risk("logs", policy_block)
    # Same signal, different allow_blocking_in_event_loop → different key → new warning
    with pytest.warns(RuntimeWarning, match="fail-fast"):
        _warn_async_risk("logs", policy_fail)


@pytest.mark.asyncio
async def test_warn_async_risk_stacklevel_is_3() -> None:
    """Kill mutants changing stacklevel=3 to stacklevel=4 or removing it."""
    policy = ExporterPolicy(retries=1, backoff_seconds=0.1, allow_blocking_in_event_loop=False)
    with patch("provide.telemetry.resilience.warnings.warn") as mock_warn:
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


def test_reset_resilience_shuts_down_executors_with_wait_false() -> None:
    """Kill mutant: shutdown(wait=True) or shutdown(wait=None)."""
    # Force executor creation for each signal
    for sig in ("logs", "traces", "metrics"):
        _get_timeout_executor(sig)

    executors = list(resilience_mod._timeout_executors.values())
    mocks = []
    for ex in executors:
        m = patch.object(ex, "shutdown", wraps=ex.shutdown)
        mocks.append(m.start())

    reset_resilience_for_tests()
    for mock_shutdown in mocks:
        mock_shutdown.assert_called_once_with(wait=False)
    patch.stopall()


# ---------------------------------------------------------------------------
# _get_timeout_executor: max_workers=4
# ---------------------------------------------------------------------------


def test_get_timeout_executor_has_2_workers_per_signal() -> None:
    """Kill mutant: max_workers=None or max_workers=3."""
    reset_resilience_for_tests()
    for sig in ("logs", "traces", "metrics"):
        executor = _get_timeout_executor(sig)
        assert executor._max_workers == 2


def test_get_timeout_executor_thread_name_prefix() -> None:
    """Kill mutant: thread_name_prefix=None or removed."""
    reset_resilience_for_tests()
    for sig in ("logs", "traces", "metrics"):
        executor = _get_timeout_executor(sig)
        assert executor._thread_name_prefix == f"provide-resilience-{sig}"


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
        result = _run_attempt_with_timeout("logs", _op, 0.0)
        mock_get.assert_not_called()
    assert result == "direct"
    assert calls["direct"] == 1


def test_run_attempt_with_timeout_negative_runs_directly() -> None:
    """Negative timeout also runs directly."""
    with patch.object(resilience_mod, "_get_timeout_executor") as mock_get:
        result = _run_attempt_with_timeout("logs", lambda: "neg", -1.0)
        mock_get.assert_not_called()
    assert result == "neg"


def test_run_attempt_with_timeout_positive_uses_executor() -> None:
    """Positive timeout uses the thread pool executor."""
    result = _run_attempt_with_timeout("traces", lambda: "pooled", 5.0)
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


# ---------------------------------------------------------------------------
# Circuit breaker: exact error message recorded in health
# ---------------------------------------------------------------------------


def test_circuit_breaker_records_exact_timeout_error_message() -> None:
    """Kill mutmut_27/30/31/32: health snapshot stores 'circuit breaker open', not None."""
    import time

    with resilience_mod._lock:
        resilience_mod._consecutive_timeouts["logs"] = resilience_mod._CIRCUIT_BREAKER_THRESHOLD
        resilience_mod._circuit_tripped_at["logs"] = time.monotonic()

    set_exporter_policy("logs", ExporterPolicy(timeout_seconds=1.0, retries=0, fail_open=True))
    run_with_resilience("logs", lambda: None)
    snap = health_mod.get_health_snapshot()
    assert snap.last_error_logs == "circuit breaker open"


def test_timeout_failure_records_actual_timeout_message() -> None:
    """Kill mutmut_60: record_export_failure(sig, exc) not (sig, None) on TimeoutError."""
    set_exporter_policy("traces", ExporterPolicy(timeout_seconds=1.0, retries=0, fail_open=True))
    with patch.object(
        resilience_mod,
        "_run_attempt_with_timeout",
        side_effect=TimeoutError("operation timed out after 1.0s"),
    ):
        run_with_resilience("traces", lambda: None)

    snap = health_mod.get_health_snapshot()
    assert snap.last_error_traces is not None
    assert snap.last_error_traces != "None"
    assert "timed out" in snap.last_error_traces


def test_general_exception_failure_records_actual_error_message() -> None:
    """Kill mutmut_77: record_export_failure(sig, exc) not (sig, None) on Exception."""
    set_exporter_policy("metrics", ExporterPolicy(retries=0, fail_open=True))

    def _raise_value_error() -> None:
        raise ValueError("boom from test")

    run_with_resilience("metrics", _raise_value_error)
    snap = health_mod.get_health_snapshot()
    assert snap.last_error_metrics == "boom from test"


@pytest.mark.asyncio
async def test_async_warning_not_raised_when_retries_zero_backoff_zero() -> None:
    """Kill mutmut_35 (retries>0→>=0) and mutmut_37 (backoff>0→>=0): no warning with retries=0, backoff=0."""
    import warnings

    from provide.telemetry.resilience import _is_running_in_event_loop

    assert _is_running_in_event_loop()
    set_exporter_policy("logs", ExporterPolicy(retries=0, backoff_seconds=0.0, timeout_seconds=0.0, fail_open=True))

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        run_with_resilience("logs", lambda: None)

    assert len(w) == 0, f"Expected no async warning but got: {[str(x.message) for x in w]}"


@pytest.mark.asyncio
async def test_async_warning_raised_when_backoff_is_nonzero() -> None:
    """Kill mutmut_38: backoff>0→>1. backoff=0.5 must trigger warning."""
    from provide.telemetry.resilience import _is_running_in_event_loop

    assert _is_running_in_event_loop()
    set_exporter_policy(
        "logs",
        ExporterPolicy(
            retries=1, backoff_seconds=0.5, timeout_seconds=0.0, allow_blocking_in_event_loop=False, fail_open=True
        ),
    )

    with pytest.warns(RuntimeWarning, match=r"fail-fast"):
        run_with_resilience("logs", lambda: None)


@pytest.mark.asyncio
async def test_in_event_loop_not_allow_blocking_no_sleep() -> None:
    """Kill mutmut_43 (backoff→None) and mutmut_44 (backoff→1.0): backoff forced to 0.0 in event loop."""
    import warnings

    from provide.telemetry.resilience import _is_running_in_event_loop

    assert _is_running_in_event_loop()
    set_exporter_policy(
        "logs",
        ExporterPolicy(
            retries=2, backoff_seconds=5.0, timeout_seconds=0.0, allow_blocking_in_event_loop=False, fail_open=True
        ),
    )

    def _always_fail() -> None:
        raise ValueError("fail")

    with patch("provide.telemetry.resilience.time.sleep") as mock_sleep, warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        run_with_resilience("logs", _always_fail)

    mock_sleep.assert_not_called()


def test_no_sleep_when_backoff_zero_after_timeout() -> None:
    """Kill mutmut_72: backoff>0→>=0 in timeout retry branch."""
    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.0, timeout_seconds=1.0, fail_open=True))
    with (
        patch.object(resilience_mod, "_run_attempt_with_timeout", side_effect=TimeoutError("timed out")),
        patch("provide.telemetry.resilience.time.sleep") as mock_sleep,
    ):
        run_with_resilience("logs", lambda: None)

    mock_sleep.assert_not_called()


def test_sleep_called_when_backoff_half_second_after_timeout() -> None:
    """Kill mutmut_73: backoff>0→>1. backoff=0.5 must call sleep."""
    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.5, timeout_seconds=1.0, fail_open=True))
    with (
        patch.object(resilience_mod, "_run_attempt_with_timeout", side_effect=TimeoutError("timed out")),
        patch("provide.telemetry.resilience.time.sleep") as mock_sleep,
    ):
        run_with_resilience("logs", lambda: None)

    mock_sleep.assert_called_once_with(0.5)


def test_sleep_called_when_backoff_half_second_after_exception() -> None:
    """Kill mutmut_87: backoff>0→>1 in general exception retry branch."""
    set_exporter_policy("logs", ExporterPolicy(retries=1, backoff_seconds=0.5, timeout_seconds=0.0, fail_open=True))

    def _always_fail() -> None:
        raise ValueError("fail")

    with patch("provide.telemetry.resilience.time.sleep") as mock_sleep:
        run_with_resilience("logs", _always_fail)

    mock_sleep.assert_called_once_with(0.5)


def test_maybe_replace_executor_shuts_down_with_wait_false() -> None:
    """Kill mutmut_14 (wait=None) and mutmut_15 (wait=True): executor must shut down with wait=False."""
    from provide.telemetry.resilience import _maybe_replace_executor

    _get_timeout_executor("logs")
    executor = resilience_mod._timeout_executors["logs"]

    with resilience_mod._lock:
        resilience_mod._consecutive_timeouts["logs"] = resilience_mod._CIRCUIT_BREAKER_THRESHOLD - 1

    with patch.object(executor, "shutdown", wraps=executor.shutdown) as mock_shutdown:
        _maybe_replace_executor("logs")
        mock_shutdown.assert_called_once_with(wait=False)


@pytest.mark.asyncio
async def test_async_warning_retries_zero_backoff_nonzero() -> None:
    """Kill mutmut_38: backoff > 0 → > 1; retries=0 so `or` depends solely on backoff."""
    assert _is_running_in_event_loop()
    set_exporter_policy(
        "logs",
        ExporterPolicy(
            retries=0,
            backoff_seconds=0.5,
            timeout_seconds=0.0,
            allow_blocking_in_event_loop=False,
            fail_open=True,
        ),
    )
    with pytest.warns(RuntimeWarning, match=r"fail-fast"):
        run_with_resilience("logs", lambda: None)


@pytest.mark.asyncio
async def test_allow_blocking_false_forces_single_attempt() -> None:
    assert _is_running_in_event_loop()
    call_count = {"n": 0}

    def _count_and_fail() -> None:
        call_count["n"] += 1
        raise ValueError("fail")

    set_exporter_policy(
        "logs",
        ExporterPolicy(
            retries=3,
            backoff_seconds=0.0,
            timeout_seconds=0.0,
            allow_blocking_in_event_loop=False,
            fail_open=True,
        ),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        run_with_resilience("logs", _count_and_fail)
    assert call_count["n"] == 1


def test_no_sleep_when_backoff_zero_after_exception() -> None:
    set_exporter_policy(
        "logs",
        ExporterPolicy(retries=1, backoff_seconds=0.0, timeout_seconds=0.0, fail_open=True),
    )

    def _fail() -> None:
        raise ValueError("fail")

    with patch("provide.telemetry.resilience.time.sleep") as mock_sleep:
        run_with_resilience("logs", _fail)
    mock_sleep.assert_not_called()
