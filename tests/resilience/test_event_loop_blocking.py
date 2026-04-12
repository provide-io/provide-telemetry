# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests that run_with_resilience() bypasses the blocking executor when called
from an active event loop (unless allow_blocking_in_event_loop=True)."""

from __future__ import annotations

import warnings
from collections.abc import Generator
from unittest.mock import patch

import pytest

from provide.telemetry.resilience import (
    ExporterPolicy,
    _get_timeout_executor,
    reset_resilience_for_tests,
    run_with_resilience,
    set_exporter_policy,
)


@pytest.fixture(autouse=True)
def _reset() -> Generator[None, None, None]:
    reset_resilience_for_tests()
    yield
    reset_resilience_for_tests()


# ── skip_executor: executor not used when in event loop ─────────────────────


@pytest.mark.asyncio
async def test_skip_executor_when_in_event_loop_no_allow() -> None:
    """Executor must not be called when inside an event loop with default policy."""
    policy = ExporterPolicy(timeout_seconds=5.0, allow_blocking_in_event_loop=False)
    set_exporter_policy("traces", policy)

    called: list[bool] = []

    def op() -> str:
        called.append(True)
        return "ok"

    with patch(
        "provide.telemetry.resilience._get_timeout_executor",
        wraps=_get_timeout_executor,
    ) as mock_exec:
        result = run_with_resilience("traces", op)

    assert result == "ok"
    assert called == [True]
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_uses_executor_when_allow_blocking_true() -> None:
    """Executor IS used when allow_blocking_in_event_loop=True."""
    policy = ExporterPolicy(timeout_seconds=5.0, allow_blocking_in_event_loop=True)
    set_exporter_policy("traces", policy)

    def op() -> str:
        return "ok"

    with patch(
        "provide.telemetry.resilience._get_timeout_executor",
        wraps=_get_timeout_executor,
    ) as mock_exec:
        result = run_with_resilience("traces", op)

    assert result == "ok"
    mock_exec.assert_called_once_with("traces")


@pytest.mark.asyncio
async def test_uses_executor_when_timeout_zero() -> None:
    """When timeout_seconds=0 no executor is used regardless of event-loop state."""
    policy = ExporterPolicy(timeout_seconds=0.0, allow_blocking_in_event_loop=False)
    set_exporter_policy("traces", policy)

    def op() -> str:
        return "ok"

    with patch(
        "provide.telemetry.resilience._get_timeout_executor",
        wraps=_get_timeout_executor,
    ) as mock_exec:
        result = run_with_resilience("traces", op)

    assert result == "ok"
    mock_exec.assert_not_called()


# ── _warn_event_loop_setup: deduplication ───────────────────────────────────


@pytest.mark.asyncio
async def test_event_loop_setup_warning_emitted_once() -> None:
    """Only one warning per signal, even across multiple calls."""
    policy = ExporterPolicy(timeout_seconds=5.0, allow_blocking_in_event_loop=False)
    set_exporter_policy("logs", policy)

    def op() -> str:
        return "ok"

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        run_with_resilience("logs", op)
        run_with_resilience("logs", op)

    event_loop_warnings = [
        x for x in w if "event loop" in str(x.message).lower() and "bypass" in str(x.message).lower()
    ]
    assert len(event_loop_warnings) == 1


@pytest.mark.asyncio
async def test_event_loop_setup_warning_per_signal() -> None:
    """Each signal independently emits one warning."""
    for sig in ("logs", "traces", "metrics"):
        policy = ExporterPolicy(timeout_seconds=5.0, allow_blocking_in_event_loop=False)
        set_exporter_policy(sig, policy)

    def op() -> str:
        return "ok"

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        run_with_resilience("logs", op)
        run_with_resilience("traces", op)
        run_with_resilience("metrics", op)

    bypass_warnings = [x for x in w if "bypass" in str(x.message).lower()]
    assert len(bypass_warnings) == 3


# ── provider warnings when called from event loop ───────────────────────────


@pytest.mark.asyncio
async def test_setup_tracing_warns_in_event_loop() -> None:
    """setup_tracing() emits RuntimeWarning when called from an event loop."""
    from provide.telemetry.config import TelemetryConfig, TracingConfig
    from provide.telemetry.tracing.provider import _reset_tracing_for_tests, setup_tracing

    _reset_tracing_for_tests()
    try:
        cfg = TelemetryConfig(service_name="svc", tracing=TracingConfig(enabled=True))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            setup_tracing(cfg)
        tracing_warns = [x for x in w if issubclass(x.category, RuntimeWarning) and "setup_tracing" in str(x.message)]
        assert len(tracing_warns) == 1
    finally:
        _reset_tracing_for_tests()


@pytest.mark.asyncio
async def test_setup_metrics_warns_in_event_loop() -> None:
    """setup_metrics() emits RuntimeWarning when called from an event loop."""
    from provide.telemetry.config import MetricsConfig, TelemetryConfig
    from provide.telemetry.metrics.provider import _set_meter_for_test, setup_metrics

    _set_meter_for_test(None)
    try:
        cfg = TelemetryConfig(service_name="svc", metrics=MetricsConfig(enabled=True))
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            setup_metrics(cfg)
        metrics_warns = [x for x in w if issubclass(x.category, RuntimeWarning) and "setup_metrics" in str(x.message)]
        assert len(metrics_warns) == 1
    finally:
        _set_meter_for_test(None)


# ── skip_executor: fractional timeout boundary ───────────────────────────────


@pytest.mark.asyncio
async def test_skip_executor_active_with_fractional_timeout() -> None:
    """timeout_seconds=0.5 must trigger skip_executor in event loop (> 0, not > 1).

    Kills: `timeout_seconds > 0` → `timeout_seconds > 1` (mutmut_7) in both
    _apply_event_loop_limits and _retry_loop.  With the mutation, 0.5 > 1 is
    False so skip_executor is False and _get_timeout_executor IS called.
    """
    policy = ExporterPolicy(timeout_seconds=0.5, allow_blocking_in_event_loop=False)
    set_exporter_policy("traces", policy)

    def op() -> str:
        return "ok"

    with patch(
        "provide.telemetry.resilience._get_timeout_executor",
        wraps=_get_timeout_executor,
    ) as mock_exec:
        result = run_with_resilience("traces", op)

    assert result == "ok"
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_retry_loop_skip_executor_false_when_timeout_zero() -> None:
    """skip_executor must be False when timeout_seconds=0 in event loop.

    Kills: `timeout_seconds > 0` → `timeout_seconds >= 0` (mutmut_6) in
    _retry_loop.  With >= 0 the flag is True for timeout=0, but the correct
    behaviour is False (no executor skip triggered purely by a zero timeout).
    """
    import provide.telemetry.resilience as _res

    seen_skip: list[bool] = []
    original_run = _res._run_attempt_with_timeout

    def _capturing(
        sig: object,
        op: object,
        timeout: float,
        *,
        skip_executor: bool = False,
    ) -> object:
        seen_skip.append(skip_executor)
        return original_run(sig, op, timeout, skip_executor=skip_executor)  # type: ignore[arg-type]

    policy = ExporterPolicy(timeout_seconds=0.0, allow_blocking_in_event_loop=False)
    set_exporter_policy("traces", policy)

    with patch("provide.telemetry.resilience._run_attempt_with_timeout", side_effect=_capturing):
        run_with_resilience("traces", lambda: "ok")

    assert seen_skip == [False], f"skip_executor must be False when timeout_seconds=0, got {seen_skip}"
