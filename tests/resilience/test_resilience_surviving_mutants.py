# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests killing surviving mutants in resilience.py.

Covers:
  _maybe_replace_executor: the predictive `get(signal, 0) + 1 >= THRESHOLD` guard
  _apply_event_loop_limits: the (1, 0.0) retry/backoff suppression inside a loop
  _retry_loop: latency ms conversion, the last_error accumulator, defensive raise
  _record_attempt_success: half-open decay resets the timeout counter to 0
  run_with_resilience: circuit-breaker error messages
  _warn_event_loop_setup: full warning text
"""

from __future__ import annotations

import asyncio
import warnings
from collections.abc import Iterator
from typing import Any, cast

import pytest

from provide.telemetry import resilience as resilience_mod
from provide.telemetry.resilience import ExporterPolicy


@pytest.fixture(autouse=True)
def _reset() -> Iterator[None]:
    resilience_mod.reset_resilience_for_tests()
    yield
    resilience_mod.reset_resilience_for_tests()


class _RecordingExecutor:
    def __init__(self) -> None:
        self.shutdown_calls: list[bool] = []

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


# ── _maybe_replace_executor: the predictive threshold ────────────────────────


def test_maybe_replace_executor_uses_zero_default_for_an_unseen_signal() -> None:
    """A signal with no recorded timeouts must read as 0, not None and not 1.

    THRESHOLD is 3, so an unseen signal predicts 0 + 1 = 1, which is below it and
    must leave the executor in place. `get(signal, None)` or a bare `get(signal)`
    would raise TypeError; `get(signal, 1)` would still be below threshold here,
    so the paired boundary test below is what pins the default's exact value.
    """
    executor = _RecordingExecutor()
    resilience_mod._timeout_executors["logs"] = cast("Any", executor)
    resilience_mod._consecutive_timeouts.pop("logs", None)

    resilience_mod._maybe_replace_executor("logs")

    assert resilience_mod._timeout_executors.get("logs") is cast("Any", executor)
    assert executor.shutdown_calls == []


def test_maybe_replace_executor_default_of_one_would_trip_at_threshold_minus_two() -> None:
    """Pin the default to 0 by driving the count to exactly THRESHOLD - 2.

    With the real default (0) the prediction is 1 + 1 = 2 < 3 → keep. A mutated
    default of 1 makes it 1 + 1 = 2 as well, so this case alone is not enough;
    the unseen-signal case above plus this one bracket the default.
    """
    executor = _RecordingExecutor()
    resilience_mod._timeout_executors["logs"] = cast("Any", executor)
    resilience_mod._consecutive_timeouts["logs"] = resilience_mod._CIRCUIT_BREAKER_THRESHOLD - 2

    resilience_mod._maybe_replace_executor("logs")

    assert resilience_mod._timeout_executors.get("logs") is cast("Any", executor)


def test_maybe_replace_executor_replaces_exactly_at_the_predicted_threshold() -> None:
    """count + 1 == THRESHOLD must replace; `+ 2` would trip one attempt early."""
    executor = _RecordingExecutor()
    resilience_mod._timeout_executors["logs"] = cast("Any", executor)
    resilience_mod._consecutive_timeouts["logs"] = resilience_mod._CIRCUIT_BREAKER_THRESHOLD - 1

    resilience_mod._maybe_replace_executor("logs")

    assert "logs" not in resilience_mod._timeout_executors
    assert executor.shutdown_calls == [False], "abandonment must not block on hung workers"


def test_maybe_replace_executor_does_not_replace_one_attempt_early() -> None:
    """`+ 2` instead of `+ 1` would replace here; the real code must not."""
    executor = _RecordingExecutor()
    resilience_mod._timeout_executors["logs"] = cast("Any", executor)
    resilience_mod._consecutive_timeouts["logs"] = resilience_mod._CIRCUIT_BREAKER_THRESHOLD - 2

    resilience_mod._maybe_replace_executor("logs")

    assert resilience_mod._timeout_executors.get("logs") is cast("Any", executor)


# ── _apply_event_loop_limits: retries suppressed inside an event loop ────────


async def test_apply_event_loop_limits_zeroes_backoff_inside_an_event_loop() -> None:
    """Inside a loop with retries configured, backoff must be exactly 0.0.

    A non-zero backoff would make the caller sleep on the event loop thread —
    the precise stall this suppression exists to prevent.
    """
    policy = ExporterPolicy(retries=3, backoff_seconds=0.5, allow_blocking_in_event_loop=False)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        attempts, backoff = resilience_mod._apply_event_loop_limits("logs", policy, 4, 0.5, 1.0)

    assert attempts == 1
    assert backoff == 0.0
    assert isinstance(backoff, float)


# ── _retry_loop: latency conversion and the error accumulator ────────────────


def test_retry_loop_converts_seconds_to_milliseconds_exactly(monkeypatch: Any) -> None:
    """latency_ms must be elapsed * 1000.0 — a 1001.0 factor is a real drift."""
    recorded: list[float] = []
    ticks = iter([10.0, 11.0])

    monkeypatch.setattr("provide.telemetry.resilience.time.perf_counter", lambda: next(ticks))
    monkeypatch.setattr(
        resilience_mod,
        "record_export_latency",
        lambda sig, latency_ms: recorded.append(latency_ms),
    )

    result = resilience_mod._retry_loop("logs", lambda: "ok", ExporterPolicy(), 1, 0.0, 0.0)

    assert result == "ok"
    assert recorded == [1000.0], "1.0s elapsed must record exactly 1000.0ms"


def test_retry_loop_raises_the_defensive_error_when_no_attempt_ran() -> None:
    """Zero attempts leaves no result and no captured error.

    The public path clamps attempts to >= 1, so this invariant is only reachable
    by calling _retry_loop directly. Pinning it keeps the accumulator's initial
    value a real None: a falsy-but-not-None initial value (e.g. "") would take
    the `raise last_error` branch and blow up with a TypeError instead.
    """
    with pytest.raises(RuntimeError, match=r"^resilience operation failed without captured error$"):
        resilience_mod._retry_loop("logs", lambda: "unused", ExporterPolicy(fail_open=False), 0, 0.0, 0.0)


def test_retry_loop_returns_none_when_no_attempt_ran_and_fail_open() -> None:
    assert resilience_mod._retry_loop("logs", lambda: "unused", ExporterPolicy(fail_open=True), 0, 0.0, 0.0) is None


# ── _record_attempt_success: half-open decay ────────────────────────────────


def test_record_attempt_success_clears_timeouts_on_half_open_probe() -> None:
    """A successful half-open probe must reset the counter to 0, not 1.

    Leaving it at 1 would keep the circuit one timeout away from re-tripping
    after a probe that proved the exporter healthy.
    """
    resilience_mod._half_open_probing["logs"] = True
    resilience_mod._consecutive_timeouts["logs"] = resilience_mod._CIRCUIT_BREAKER_THRESHOLD
    resilience_mod._open_count["logs"] = 2

    resilience_mod._record_attempt_success("logs")

    assert resilience_mod._consecutive_timeouts["logs"] == 0
    assert resilience_mod._half_open_probing["logs"] is False
    assert resilience_mod._open_count["logs"] == 1


# ── run_with_resilience: circuit-breaker messages ───────────────────────────


def test_open_circuit_raises_with_the_documented_message(monkeypatch: Any) -> None:
    monkeypatch.setattr(resilience_mod, "_check_circuit_breaker", lambda sig: True)
    resilience_mod.set_exporter_policy("logs", ExporterPolicy(timeout_seconds=1.0, fail_open=False))

    with pytest.raises(TimeoutError) as excinfo:
        resilience_mod.run_with_resilience("logs", lambda: "never")

    assert str(excinfo.value) == "circuit breaker open: too many consecutive timeouts"


def test_open_circuit_records_failure_with_the_documented_message(monkeypatch: Any) -> None:
    seen: list[str] = []
    monkeypatch.setattr(resilience_mod, "_check_circuit_breaker", lambda sig: True)
    monkeypatch.setattr(
        resilience_mod,
        "record_export_failure",
        lambda sig, exc: seen.append(str(exc)),
    )
    resilience_mod.set_exporter_policy("logs", ExporterPolicy(timeout_seconds=1.0, fail_open=True))

    assert resilience_mod.run_with_resilience("logs", lambda: "never") is None
    assert seen == ["circuit breaker open"]


# ── _warn_event_loop_setup: full warning text ───────────────────────────────


def test_warn_event_loop_setup_emits_the_full_documented_message() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resilience_mod._warn_event_loop_setup("traces")

    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert str(caught[0].message) == (
        "telemetry traces export called from an active event loop with "
        "timeout_seconds > 0 and allow_blocking_in_event_loop=False; "
        "bypassing timeout executor to prevent event loop stall. "
        "Call setup_telemetry() before starting the event loop."
    )


def test_warn_event_loop_setup_warns_once_per_signal() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resilience_mod._warn_event_loop_setup("metrics")
        resilience_mod._warn_event_loop_setup("metrics")

    assert len(caught) == 1


def test_event_loop_detection_is_true_inside_a_running_loop() -> None:
    async def _inside() -> bool:
        return resilience_mod._is_running_in_event_loop()

    assert asyncio.run(_inside()) is True
    assert resilience_mod._is_running_in_event_loop() is False


def test_maybe_replace_executor_default_is_zero_not_one(monkeypatch: Any) -> None:
    """An unseen signal must predict 0 + 1, not 1 + 1.

    With THRESHOLD lowered to 2 the two defaults diverge: the real default keeps
    the executor (1 < 2) while a default of 1 would abandon it (2 >= 2).
    """
    monkeypatch.setattr(resilience_mod, "_CIRCUIT_BREAKER_THRESHOLD", 2)
    executor = _RecordingExecutor()
    resilience_mod._timeout_executors["logs"] = cast("Any", executor)
    resilience_mod._consecutive_timeouts.pop("logs", None)

    resilience_mod._maybe_replace_executor("logs")

    assert resilience_mod._timeout_executors.get("logs") is cast("Any", executor)
    assert executor.shutdown_calls == []


def test_warn_async_risk_allowing_blocking_emits_the_full_message() -> None:
    policy = ExporterPolicy(allow_blocking_in_event_loop=True, retries=2)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resilience_mod._warn_async_risk("logs", policy)

    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert str(caught[0].message) == (
        "resilience policy for logs allows blocking behavior in an active event loop (retries/backoff configured)"
    )


def test_warn_async_risk_fail_fast_emits_the_full_message() -> None:
    policy = ExporterPolicy(allow_blocking_in_event_loop=False, retries=2)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resilience_mod._warn_async_risk("traces", policy)

    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert str(caught[0].message) == (
        "resilience policy for traces uses retries/backoff in an active event loop; "
        "forcing fail-fast behavior for this call"
    )


def test_warn_async_risk_warns_once_per_signal_and_policy_mode() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resilience_mod._warn_async_risk("metrics", ExporterPolicy(allow_blocking_in_event_loop=True))
        resilience_mod._warn_async_risk("metrics", ExporterPolicy(allow_blocking_in_event_loop=True))
        resilience_mod._warn_async_risk("metrics", ExporterPolicy(allow_blocking_in_event_loop=False))

    assert len(caught) == 2, "the two policy modes warn separately, each only once"


# ── warning attribution: stacklevel must blame the caller, not the emitter ───


def _captured_warn_calls(monkeypatch: Any) -> list[dict[str, Any]]:
    """Patch warnings.warn and record each call's kwargs.

    Asserting on the recorded frame (filename/lineno) instead would be wrong here:
    mutmut runs the code through a trampoline that adds a stack frame, so frame
    identity shifts under mutation. Capturing the stacklevel argument pins the
    literal directly and is unaffected.
    """
    calls: list[dict[str, Any]] = []

    def fake_warn(message: object, category: object = None, stacklevel: int = 1, **kw: Any) -> None:
        calls.append({"message": str(message), "category": category, "stacklevel": stacklevel})

    monkeypatch.setattr("provide.telemetry.resilience.warnings.warn", fake_warn)
    return calls


def test_warn_async_risk_blames_the_callers_caller(monkeypatch: Any) -> None:
    """stacklevel=3 points past _warn_async_risk and its caller to the real origin.

    Dropping the argument (stacklevel=1) blames resilience.py itself; 4 overshoots
    into the framework. Either way the operator is pointed at the wrong place.
    """
    calls = _captured_warn_calls(monkeypatch)

    resilience_mod._warn_async_risk("logs", ExporterPolicy(allow_blocking_in_event_loop=True))
    resilience_mod._warn_async_risk("traces", ExporterPolicy(allow_blocking_in_event_loop=False))

    assert [c["stacklevel"] for c in calls] == [3, 3]
    assert all(c["category"] is RuntimeWarning for c in calls)


def test_warn_event_loop_setup_blames_three_frames_up(monkeypatch: Any) -> None:
    """stacklevel=4 reaches the caller of run_with_resilience, not the internals."""
    calls = _captured_warn_calls(monkeypatch)

    resilience_mod._warn_event_loop_setup("logs")

    assert [c["stacklevel"] for c in calls] == [4]
    assert calls[0]["category"] is RuntimeWarning
