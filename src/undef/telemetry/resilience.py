# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Exporter retry/backoff and failure-policy helpers."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from undef.telemetry.health import (
    increment_async_blocking_risk,
    increment_retries,
    record_export_failure,
    record_export_success,
)

T = TypeVar("T")
Signal = str


@dataclass(frozen=True)
class ExporterPolicy:
    retries: int = 0
    backoff_seconds: float = 0.0
    timeout_seconds: float = 10.0
    fail_open: bool = True
    allow_blocking_in_event_loop: bool = False


_CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive timeouts before tripping
_CIRCUIT_BREAKER_COOLDOWN = 30.0  # seconds before allowing a half-open probe

_lock = threading.Lock()
_policies: dict[Signal, ExporterPolicy] = {
    "logs": ExporterPolicy(),
    "traces": ExporterPolicy(),
    "metrics": ExporterPolicy(),
}
_consecutive_timeouts: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_circuit_tripped_at: dict[Signal, float] = {"logs": 0.0, "traces": 0.0, "metrics": 0.0}
_async_warned_signals: set[Signal] = set()


def set_exporter_policy(signal: Signal, policy: ExporterPolicy) -> None:
    sig = signal if signal in _policies else "logs"
    with _lock:
        _policies[sig] = policy


def get_exporter_policy(signal: Signal) -> ExporterPolicy:
    sig = signal if signal in _policies else "logs"
    with _lock:
        return _policies[sig]


def run_with_resilience(signal: Signal, operation: Callable[[], T]) -> T | None:
    sig = _validate_signal(signal)
    policy = get_exporter_policy(sig)
    attempts = max(1, policy.retries + 1)
    backoff_seconds = policy.backoff_seconds
    timeout_seconds = max(0.0, policy.timeout_seconds)
    # Circuit breaker: skip work if the pool is likely saturated.
    if timeout_seconds > 0:
        with _lock:
            if _consecutive_timeouts[sig] >= _CIRCUIT_BREAKER_THRESHOLD:
                elapsed = time.monotonic() - _circuit_tripped_at[sig]
                if elapsed < _CIRCUIT_BREAKER_COOLDOWN:
                    record_export_failure(sig, TimeoutError("circuit breaker open"))  # pragma: no mutate
                    if policy.fail_open:
                        return None
                    raise TimeoutError("circuit breaker open: too many consecutive timeouts")  # pragma: no mutate
                # Half-open: cooldown expired, allow one probe attempt through
    if _is_running_in_event_loop() and (policy.retries > 0 or policy.backoff_seconds > 0):  # pragma: no mutate
        increment_async_blocking_risk(sig)  # pragma: no mutate
        _warn_async_risk(sig, policy)  # pragma: no mutate
        if not policy.allow_blocking_in_event_loop:
            attempts = 1
            backoff_seconds = 0.0
    last_error: Exception | None = None
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            result = _run_attempt_with_timeout(operation, timeout_seconds)
            latency_ms = (time.perf_counter() - started) * 1000.0  # pragma: no mutate
            record_export_success(sig, latency_ms=latency_ms)  # pragma: no mutate
            with _lock:
                _consecutive_timeouts[sig] = 0
            return result
        except TimeoutError as exc:
            last_error = exc
            record_export_failure(sig, exc)  # pragma: no mutate
            with _lock:
                _consecutive_timeouts[sig] += 1
                if _consecutive_timeouts[sig] >= _CIRCUIT_BREAKER_THRESHOLD:
                    _circuit_tripped_at[sig] = time.monotonic()
            if attempt < attempts - 1:
                increment_retries(sig)
                if backoff_seconds > 0:  # pragma: no mutate
                    time.sleep(backoff_seconds)
        except Exception as exc:
            last_error = exc
            record_export_failure(sig, exc)  # pragma: no mutate
            with _lock:
                _consecutive_timeouts[sig] = 0
            if attempt < attempts - 1:
                increment_retries(sig)
                if backoff_seconds > 0:  # pragma: no mutate
                    time.sleep(backoff_seconds)
    if policy.fail_open:
        return None
    if last_error is not None:
        raise last_error
    raise RuntimeError("resilience operation failed without captured error")  # pragma: no cover


def _run_attempt_with_timeout(operation: Callable[[], T], timeout_seconds: float) -> T:
    if timeout_seconds <= 0:
        return operation()
    outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def _target() -> None:
        try:
            outcome.put((True, operation()))
        except Exception as exc:  # pragma: no cover - exercised by caller path
            outcome.put((False, exc))

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TimeoutError(f"operation timed out after {timeout_seconds}s")
    ok, payload = outcome.get_nowait()
    if ok:
        return cast(T, payload)
    if isinstance(payload, Exception):
        raise payload
    raise RuntimeError("timeout worker returned invalid exception payload")


def reset_resilience_for_tests() -> None:
    with _lock:
        for signal in ("logs", "traces", "metrics"):
            _policies[signal] = ExporterPolicy()
            _consecutive_timeouts[signal] = 0
            _circuit_tripped_at[signal] = 0.0
        _async_warned_signals.clear()


def _is_running_in_event_loop() -> bool:
    try:
        _ = asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _warn_async_risk(signal: Signal, policy: ExporterPolicy) -> None:
    sig = signal if signal in {"logs", "traces", "metrics"} else "logs"
    with _lock:
        if sig in _async_warned_signals:
            return
        _async_warned_signals.add(sig)
    if policy.allow_blocking_in_event_loop:
        warnings.warn(
            (
                f"resilience policy for {sig} allows blocking behavior in an active event loop "
                "(retries/backoff configured)"
            ),
            RuntimeWarning,
            stacklevel=3,
        )
        return
    warnings.warn(
        (
            f"resilience policy for {sig} uses retries/backoff in an active event loop; "
            "forcing fail-fast behavior for this call"
        ),
        RuntimeWarning,
        stacklevel=3,
    )
