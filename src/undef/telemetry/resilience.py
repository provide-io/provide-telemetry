# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Exporter retry/backoff and failure-policy helpers."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from undef.telemetry.health import increment_retries, record_export_failure, record_export_success

T = TypeVar("T")
Signal = str


@dataclass(frozen=True)
class ExporterPolicy:
    retries: int = 0
    backoff_seconds: float = 0.0
    timeout_seconds: float = 10.0
    fail_open: bool = True


_lock = threading.Lock()
_policies: dict[Signal, ExporterPolicy] = {
    "logs": ExporterPolicy(),
    "traces": ExporterPolicy(),
    "metrics": ExporterPolicy(),
}


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
                if policy.backoff_seconds > 0:
                    time.sleep(policy.backoff_seconds)
    if policy.fail_open:
        return None
    if last_error is not None:
        raise last_error
    raise RuntimeError("resilience operation failed without captured error")  # pragma: no cover


def reset_resilience_for_tests() -> None:
    with _lock:
        for signal in ("logs", "traces", "metrics"):
            _policies[signal] = ExporterPolicy()
