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
    record_export_success,
)

T = TypeVar("T")
Signal = str


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
# Per-signal executors isolate failure domains so a timeout storm in one
# signal (e.g. traces) cannot starve workers used by another (e.g. logs).
_timeout_executors: dict[Signal, concurrent.futures.ThreadPoolExecutor] = {}


def _get_timeout_executor(signal: Signal) -> concurrent.futures.ThreadPoolExecutor:
    with _lock:
        executor = _timeout_executors.get(signal)
        if executor is None:
            prefix = f"provide-resilience-{signal}"  # pragma: no mutate
            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=2,
                thread_name_prefix=prefix,  # pragma: no mutate
            )
            _timeout_executors[signal] = executor
        return executor


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
            _half_open_probing[sig] = (
                False  # pragma: no mutate — False/None both falsy; dict truthiness check is equivalent
            )
            _consecutive_timeouts[sig] = 0
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
            record_export_failure(sig, TimeoutError("circuit breaker open"))
            if policy.fail_open:
                return None
            raise TimeoutError("circuit breaker open: too many consecutive timeouts")  # pragma: no mutate
    if _is_running_in_event_loop() and (policy.retries > 0 or policy.backoff_seconds > 0):
        increment_async_blocking_risk(sig)
        _warn_async_risk(sig, policy)  # pragma: no mutate
        if not policy.allow_blocking_in_event_loop:
            attempts = 1
            backoff_seconds = 0.0  # pragma: no mutate
    last_error: Exception | None = None  # pragma: no mutate
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            result = _run_attempt_with_timeout(sig, operation, timeout_seconds)  # pragma: no mutate
            latency_ms = (time.perf_counter() - started) * 1000.0  # pragma: no mutate
            record_export_success(sig, latency_ms=latency_ms)
            _record_attempt_success(sig)
            return result
        except TimeoutError as exc:
            last_error = exc
            record_export_failure(sig, exc)
            _record_attempt_failure(sig, is_timeout=True)
            if attempt < attempts - 1:
                increment_retries(sig)
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds)
        except Exception as exc:
            last_error = exc
            record_export_failure(sig, exc)
            _record_attempt_failure(
                sig, is_timeout=False
            )  # pragma: no mutate — False/None both falsy in elif is_timeout check
            if attempt < attempts - 1:
                increment_retries(sig)
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds)
    if policy.fail_open:
        return None
    if last_error is not None:
        raise last_error
    raise RuntimeError("resilience operation failed without captured error")  # pragma: no cover  # pragma: no mutate


def _run_attempt_with_timeout(signal: Signal, operation: Callable[[], T], timeout_seconds: float) -> T:
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
    if timeout_seconds <= 0:
        return operation()
    executor = _get_timeout_executor(signal)  # pragma: no mutate
    future = executor.submit(operation)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError:
        future.cancel()
        _maybe_replace_executor(signal)
        raise TimeoutError(f"operation timed out after {timeout_seconds}s") from None


def _maybe_replace_executor(signal: Signal) -> None:
    """Replace the executor if the circuit breaker has tripped.

    This abandons ghost threads stuck in the old pool and gives the next
    half-open probe a clean executor with no hung workers.
    """
    with _lock:
        if _consecutive_timeouts.get(signal, 0) + 1 >= _CIRCUIT_BREAKER_THRESHOLD:  # pragma: no mutate
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
            if (
                remaining > 0
            ):  # pragma: no mutate — boundary equivalence: >0 vs >=0 (P=0 exact float match) and >0 vs >1 (sub-ms timing artifact)
                return ("open", _open_count[sig], remaining)
            return ("half-open", _open_count[sig], 0.0)
        return ("closed", _open_count[sig], 0.0)


def reset_resilience_for_tests() -> None:
    with _lock:
        for signal in ("logs", "traces", "metrics"):
            _policies[signal] = ExporterPolicy()
            _consecutive_timeouts[signal] = 0
            _circuit_tripped_at[signal] = 0.0
            _open_count[signal] = 0
            _half_open_probing[signal] = False
        _async_warned_signals.clear()
        for executor in _timeout_executors.values():
            executor.shutdown(wait=False)
        _timeout_executors.clear()


def _is_running_in_event_loop() -> bool:
    try:
        _ = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _warn_async_risk(signal: Signal, policy: ExporterPolicy) -> None:
    key = (signal, policy.allow_blocking_in_event_loop)
    with _lock:
        if key in _async_warned_signals:
            return
        _async_warned_signals.add(key)
    if policy.allow_blocking_in_event_loop:
        warnings.warn(  # pragma: no mutate
            (
                f"resilience policy for {signal} allows blocking behavior in an active event loop "
                "(retries/backoff configured)"  # pragma: no mutate
            ),
            RuntimeWarning,
            stacklevel=3,  # pragma: no mutate
        )
        return
    warnings.warn(  # pragma: no mutate
        (
            f"resilience policy for {signal} uses retries/backoff in an active event loop; "
            "forcing fail-fast behavior for this call"  # pragma: no mutate
        ),
        RuntimeWarning,
        stacklevel=3,  # pragma: no mutate
    )
