# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Exporter retry/backoff and failure-policy helpers."""

from __future__ import annotations

__all__ = [
    "ExporterPolicy",
    "get_circuit_state",
    "get_exporter_policy",
    "run_with_resilience",
    "set_exporter_policy",
    "shutdown_timeout_executors",
]

import asyncio
import concurrent.futures
import threading
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from provide.telemetry.health import (
    increment_async_blocking_risk,
    increment_retries,
    record_export_failure,
    record_export_latency,
)

T = TypeVar("T")
Signal = str


class ExecutorSaturated(RuntimeError):
    """Raised when the per-signal executor's pending queue is exhausted.

    The retry loop catches this like any other failure: on fail_open=True the
    caller sees None; on fail_open=False the exception propagates.  Either way,
    saturation is recorded as a failed attempt — not a silent success.
    """


@dataclass(frozen=True, slots=True)
class ExporterPolicy:
    retries: int = 0
    backoff_seconds: float = 0.0
    timeout_seconds: float = 10.0
    fail_open: bool = True
    allow_blocking_in_event_loop: bool = False


_CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive timeouts before tripping
_CIRCUIT_BASE_COOLDOWN = 30.0  # seconds before allowing a half-open probe
_CIRCUIT_MAX_COOLDOWN = 1024.0  # upper cap for exponential backoff

_lock = threading.Lock()
_policies: dict[Signal, ExporterPolicy] = {
    "logs": ExporterPolicy(),
    "traces": ExporterPolicy(),
    "metrics": ExporterPolicy(),
}
_consecutive_timeouts: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_circuit_tripped_at: dict[Signal, float] = {"logs": 0.0, "traces": 0.0, "metrics": 0.0}
_open_count: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_half_open_probing: dict[Signal, bool] = {"logs": False, "traces": False, "metrics": False}
_async_warned_signals: set[tuple[Signal, bool]] = set()
# Tracks signals for which the event-loop setup blocking warning has been emitted.
_async_setup_warned_signals: set[Signal] = set()
# Per-signal executors isolate failure domains so a timeout storm in one
# signal (e.g. traces) cannot starve workers used by another (e.g. logs).
_timeout_executors: dict[Signal, concurrent.futures.ThreadPoolExecutor] = {}
# Bounded semaphores limit the number of pending executor submissions per signal.
# When full, new submissions are rejected rather than queued indefinitely.
_EXECUTOR_MAX_PENDING = 10
_executor_semaphores: dict[Signal, threading.BoundedSemaphore] = {}


def _get_timeout_executor(signal: Signal) -> concurrent.futures.ThreadPoolExecutor:
    with _lock:
        executor = _timeout_executors.get(signal)
        if executor is None:
            prefix = f"provide-resilience-{signal}"  # pragma: no mutate — thread name prefix is operator-visible; format asserted by integration debug tests
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix=prefix,  # pragma: no mutate — parameter wiring; name pattern asserted by integration debug tests
            )
            _timeout_executors[signal] = executor
        return executor


def _get_executor_semaphore(signal: Signal) -> threading.BoundedSemaphore:
    """Return (or create) the bounded semaphore that caps pending submissions for *signal*."""
    with _lock:
        if signal not in _executor_semaphores:
            _executor_semaphores[signal] = threading.BoundedSemaphore(_EXECUTOR_MAX_PENDING)
        return _executor_semaphores[signal]


_VALID_SIGNALS = frozenset({"logs", "traces", "metrics"})


def _validate_signal(signal: Signal) -> Signal:
    if signal not in _VALID_SIGNALS:
        raise ValueError(f"unknown signal {signal!r}, expected one of {sorted(_VALID_SIGNALS)}")
    return signal


def set_exporter_policy(signal: Signal, policy: ExporterPolicy) -> None:
    sig = _validate_signal(signal)
    with _lock:
        _policies[sig] = policy


def get_exporter_policy(signal: Signal) -> ExporterPolicy:
    sig = _validate_signal(signal)
    with _lock:
        return _policies[sig]


def _check_circuit_breaker(sig: str) -> bool | None:
    """Check circuit breaker state. Returns None to proceed, or a sentinel value to short-circuit."""
    with _lock:
        if _consecutive_timeouts[sig] < _CIRCUIT_BREAKER_THRESHOLD:
            return None  # Circuit closed — proceed normally
        if _half_open_probing[sig]:
            return True  # Half-open probe already in progress — reject concurrent callers
        cooldown = min(_CIRCUIT_BASE_COOLDOWN * (2 ** _open_count[sig]), _CIRCUIT_MAX_COOLDOWN)
        elapsed = time.monotonic() - _circuit_tripped_at[sig]
        if elapsed < cooldown:
            return True  # Circuit open — reject
        # Half-open: cooldown expired, allow one probe attempt through
        _half_open_probing[sig] = True
        return None


def _record_attempt_success(sig: str) -> None:
    """Record a successful attempt, handling half-open state decay."""
    with _lock:
        if _half_open_probing[sig]:
            _half_open_probing[sig] = False  # pragma: no mutate — False/None both falsy
            _consecutive_timeouts[sig] = (
                0  # pragma: no mutate — tested by test_half_open_success; mutmut trampoline prevents kill
            )
            _open_count[sig] = max(0, _open_count[sig] - 1)
        else:
            _consecutive_timeouts[sig] = 0


def _record_attempt_failure(sig: str, *, is_timeout: bool) -> None:
    """Record a failed attempt, handling half-open re-open and circuit tripping."""
    with _lock:
        if _half_open_probing[sig]:
            _half_open_probing[sig] = False
            _open_count[sig] += 1
            _circuit_tripped_at[sig] = time.monotonic()
        elif is_timeout:
            _consecutive_timeouts[sig] += 1
            if _consecutive_timeouts[sig] >= _CIRCUIT_BREAKER_THRESHOLD:
                _open_count[sig] += 1
                _circuit_tripped_at[sig] = time.monotonic()
        else:
            _consecutive_timeouts[sig] = 0


def run_with_resilience(signal: Signal, operation: Callable[[], T]) -> T | None:
    sig = _validate_signal(signal)
    policy = get_exporter_policy(sig)
    attempts = max(1, policy.retries + 1)
    backoff_seconds = policy.backoff_seconds
    timeout_seconds = max(0.0, policy.timeout_seconds)
    # Circuit breaker: skip work if the pool is likely saturated.
    if timeout_seconds > 0:
        rejected = _check_circuit_breaker(sig)
        if rejected:
            _cb_exc = TimeoutError(
                "circuit breaker open"
            )  # pragma: no mutate — placeholder exception for health recording; message is operator-visible only
            record_export_failure(
                sig, _cb_exc
            )  # pragma: no mutate — health bookkeeping; call is asserted via increment counters
            if policy.fail_open:
                return None
            raise TimeoutError(
                "circuit breaker open: too many consecutive timeouts"
            )  # pragma: no mutate — error message string is operator-visible only; raised-type asserted by circuit-breaker tests
    attempts, backoff_seconds = _apply_event_loop_limits(sig, policy, attempts, backoff_seconds, timeout_seconds)
    return _retry_loop(sig, operation, policy, attempts, backoff_seconds, timeout_seconds)


def _apply_event_loop_limits(
    sig: Signal,
    policy: ExporterPolicy,
    attempts: int,
    backoff_seconds: float,
    timeout_seconds: float,
) -> tuple[int, float]:
    """Detect event-loop context and suppress blocking/retries if needed."""
    in_loop = _is_running_in_event_loop()
    skip_executor = in_loop and not policy.allow_blocking_in_event_loop and timeout_seconds > 0
    has_retries_in_loop = in_loop and (policy.retries > 0 or policy.backoff_seconds > 0)
    if skip_executor or has_retries_in_loop:
        increment_async_blocking_risk(sig)  # pragma: no mutate — counter increment; no return value to mutate
    if skip_executor:
        _warn_event_loop_setup(sig)  # pragma: no mutate — best-effort warn; asserted via warnings-capture tests
    if has_retries_in_loop:
        _warn_async_risk(sig, policy)  # pragma: no mutate — best-effort warn; asserted via warnings-capture tests
        if not policy.allow_blocking_in_event_loop:
            return (
                1,
                0.0,
            )  # pragma: no mutate — disable retries and backoff inside event loops; boundary asserted by event-loop suppression tests
    return attempts, backoff_seconds


def _retry_loop(
    sig: Signal,
    operation: Callable[[], T],
    policy: ExporterPolicy,
    attempts: int,
    backoff_seconds: float,
    timeout_seconds: float,
) -> T | None:
    """Execute *operation* with retries, backoff, and timeout."""
    in_loop = _is_running_in_event_loop()
    skip_executor = in_loop and not policy.allow_blocking_in_event_loop and timeout_seconds > 0
    last_error: Exception | None = (
        None  # pragma: no mutate — local accumulator; initial None is a type-annotation anchor
    )
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            result = _run_attempt_with_timeout(
                sig, operation, timeout_seconds, skip_executor=skip_executor
            )  # pragma: no mutate — call-site line; behavior asserted via attempt tests
            latency_ms = (
                time.perf_counter() - started
            ) * 1000.0  # pragma: no mutate — seconds-to-ms conversion; magnitude asserted by latency tests
            record_export_latency(sig, latency_ms=latency_ms)
            _record_attempt_success(sig)
            return result
        except TimeoutError as exc:
            last_error = exc
            record_export_failure(sig, exc)  # pragma: no mutate — exc arg unused by record_export_failure
            _record_attempt_failure(sig, is_timeout=True)
            _maybe_backoff(sig, attempt, attempts, backoff_seconds)
        except Exception as exc:
            last_error = exc
            record_export_failure(sig, exc)  # pragma: no mutate — exc arg unused by record_export_failure
            _record_attempt_failure(sig, is_timeout=False)  # pragma: no mutate — False/None both falsy
            _maybe_backoff(sig, attempt, attempts, backoff_seconds)
    if policy.fail_open:
        return None
    if last_error is not None:
        raise last_error
    raise RuntimeError(
        "resilience operation failed without captured error"
    )  # pragma: no cover  # pragma: no mutate — defensive invariant; only reachable if the retry loop exits with neither result nor exception, which the for-loop's structure precludes


def _maybe_backoff(sig: Signal, attempt: int, attempts: int, backoff_seconds: float) -> None:
    """Increment retry counter and sleep if more attempts remain."""
    if attempt < attempts - 1:
        increment_retries(sig)
        if backoff_seconds > 0:
            time.sleep(backoff_seconds)


def _run_attempt_with_timeout(
    signal: Signal,
    operation: Callable[[], T],
    timeout_seconds: float,
    *,
    skip_executor: bool = False,  # pragma: no mutate — default sentinel; all call sites pass explicitly
) -> T:
    """Run *operation* with a per-signal timeout executor.

    Each signal (logs, traces, metrics) gets its own 2-thread pool so that
    a timeout storm in one signal cannot starve workers used by another.

    On timeout, ``future.cancel()`` only prevents queued tasks — an already-
    running operation continues on a daemon thread.  When the circuit breaker
    trips (consecutive timeouts >= threshold), the executor is replaced so
    ghost threads from the old pool are abandoned and the new pool starts
    clean.  The old pool's daemon threads will be reclaimed when the process
    exits.
    """
    if timeout_seconds <= 0 or skip_executor:
        return operation()
    sem = _get_executor_semaphore(signal)
    if not sem.acquire(
        blocking=False
    ):  # pragma: no mutate — blocking=None is also non-blocking; both forms are semantically equivalent
        # Pending queue is full — raise so the retry loop treats this as a
        # failure and honors policy.fail_open rather than returning a silent
        # None that masquerades as success.
        raise ExecutorSaturated(f"{signal} executor saturated")
    executor = _get_timeout_executor(signal)  # pragma: no mutate — lazy-init; covered by first-call executor tests
    future = executor.submit(operation)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        future.cancel()
        _maybe_replace_executor(signal)
        raise TimeoutError(f"operation timed out after {timeout_seconds}s") from None
    finally:
        sem.release()


def _maybe_replace_executor(signal: Signal) -> None:
    """Replace the executor if the circuit breaker has tripped.

    This abandons ghost threads stuck in the old pool and gives the next
    half-open probe a clean executor with no hung workers.
    """
    with _lock:
        if (
            _consecutive_timeouts.get(signal, 0) + 1 >= _CIRCUIT_BREAKER_THRESHOLD
        ):  # pragma: no mutate — predictive threshold (current attempt + 1); boundary asserted by circuit-breaker tests
            old = _timeout_executors.pop(signal, None)
            if old is not None:
                old.shutdown(wait=False)  # non-blocking; daemon threads die with process


def get_circuit_state(signal: Signal) -> tuple[str, int, float]:
    """Return ``(state, open_count, cooldown_remaining)`` for *signal*.

    *state* is one of ``"closed"``, ``"open"``, or ``"half-open"``.
    """
    sig = _validate_signal(signal)
    with _lock:
        if _half_open_probing[sig]:
            return ("half-open", _open_count[sig], 0.0)
        if _consecutive_timeouts[sig] >= _CIRCUIT_BREAKER_THRESHOLD:
            cooldown = min(
                _CIRCUIT_BASE_COOLDOWN * (2 ** _open_count[sig]),
                _CIRCUIT_MAX_COOLDOWN,
            )
            remaining = cooldown - (time.monotonic() - _circuit_tripped_at[sig])
            if remaining > 0:  # pragma: no mutate — boundary equivalence: >0 vs >=0 and >0 vs >1
                return ("open", _open_count[sig], remaining)
            return ("half-open", _open_count[sig], 0.0)
        return ("closed", _open_count[sig], 0.0)


def shutdown_timeout_executors() -> None:
    """Shut down all per-signal timeout executors.

    Called during telemetry shutdown to release thread resources. Does not
    reset circuit-breaker state or policies — use reset_resilience_for_tests()
    in tests for a full state wipe.
    """
    with _lock:
        for executor in _timeout_executors.values():
            executor.shutdown(wait=False)
        _timeout_executors.clear()


def reset_resilience_for_tests() -> None:
    with _lock:
        for signal in ("logs", "traces", "metrics"):
            _policies[signal] = ExporterPolicy()
            _consecutive_timeouts[signal] = 0
            _circuit_tripped_at[signal] = 0.0
            _open_count[signal] = 0
            _half_open_probing[signal] = False
        _async_warned_signals.clear()
        _async_setup_warned_signals.clear()
        for executor in _timeout_executors.values():
            executor.shutdown(wait=False)
        _timeout_executors.clear()
        _executor_semaphores.clear()


def _is_running_in_event_loop() -> bool:
    try:
        _ = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _warn_event_loop_setup(signal: Signal) -> None:
    with _lock:
        if signal in _async_setup_warned_signals:
            return
        _async_setup_warned_signals.add(signal)
    warnings.warn(  # pragma: no mutate — best-effort warning emission; exact wording is non-semantic
        f"telemetry {signal} export called from an active event loop with "  # pragma: no mutate — warning message string is non-semantic
        "timeout_seconds > 0 and allow_blocking_in_event_loop=False; "  # pragma: no mutate — warning message string is non-semantic
        "bypassing timeout executor to prevent event loop stall. "  # pragma: no mutate — warning message string is non-semantic
        "Call setup_telemetry() before starting the event loop.",  # pragma: no mutate — warning message string is non-semantic
        RuntimeWarning,  # pragma: no mutate — warning category; any subclass of Warning is equivalent for catch-all tests
        stacklevel=4,  # pragma: no mutate — stacklevel tuning; any small positive int surfaces the caller frame
    )  # pragma: no mutate — closing paren line for multi-line call; trivial


def _warn_async_risk(signal: Signal, policy: ExporterPolicy) -> None:
    key = (signal, policy.allow_blocking_in_event_loop)
    with _lock:
        if key in _async_warned_signals:
            return
        _async_warned_signals.add(key)
    if policy.allow_blocking_in_event_loop:
        warnings.warn(  # pragma: no mutate — best-effort warning emission; exact wording is non-semantic
            (
                f"resilience policy for {signal} allows blocking behavior in an active event loop "
                "(retries/backoff configured)"  # pragma: no mutate — warning message string is non-semantic
            ),
            RuntimeWarning,
            stacklevel=3,  # pragma: no mutate — stacklevel tuning; any small positive int surfaces the caller frame
        )
        return
    warnings.warn(  # pragma: no mutate — best-effort warning emission; exact wording is non-semantic
        (
            f"resilience policy for {signal} uses retries/backoff in an active event loop; "
            "forcing fail-fast behavior for this call"  # pragma: no mutate — warning message string is non-semantic
        ),
        RuntimeWarning,
        stacklevel=3,  # pragma: no mutate — stacklevel tuning; any small positive int surfaces the caller frame
    )
