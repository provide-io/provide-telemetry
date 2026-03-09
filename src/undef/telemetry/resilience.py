# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Exporter retry/backoff and failure-policy helpers."""

from __future__ import annotations

import asyncio
import threading
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

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


_lock = threading.Lock()
_policies: dict[Signal, ExporterPolicy] = {
    "logs": ExporterPolicy(),
    "traces": ExporterPolicy(),
    "metrics": ExporterPolicy(),
}
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
    policy = get_exporter_policy(signal)
    attempts = max(1, policy.retries + 1)
    backoff_seconds = policy.backoff_seconds
    if _is_running_in_event_loop() and (policy.retries > 0 or policy.backoff_seconds > 0):
        increment_async_blocking_risk(signal)
        _warn_async_risk(signal, policy)
        if not policy.allow_blocking_in_event_loop:
            attempts = 1
            backoff_seconds = 0.0
    last_error: Exception | None = None
    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            result = operation()
            latency_ms = (time.perf_counter() - started) * 1000.0
            record_export_success(signal, latency_ms=latency_ms)
            return result
        except Exception as exc:  # pragma: no cover - specific paths covered in tests
            last_error = exc
            record_export_failure(signal, exc)
            if attempt < attempts - 1:
                increment_retries(signal)
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds)
    if policy.fail_open:
        return None
    if last_error is not None:
        raise last_error
    raise RuntimeError("resilience operation failed without captured error")  # pragma: no cover


def reset_resilience_for_tests() -> None:
    with _lock:
        for signal in ("logs", "traces", "metrics"):
            _policies[signal] = ExporterPolicy()
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
