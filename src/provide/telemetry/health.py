# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Internal self-observability counters and snapshot API."""

from __future__ import annotations

__all__ = [
    "HealthSnapshot",
    "get_health_snapshot",
    "increment_async_blocking_risk",
    "increment_dropped",
    "increment_emitted",
    "increment_retries",
    "record_export_failure",
    "record_export_latency",
    "set_setup_error",
]

import threading
import types
from typing import NamedTuple

Signal = str


class HealthSnapshot(NamedTuple):
    """Canonical 25-field health snapshot.

    NamedTuple instead of frozen dataclass for ~3x faster construction
    (25 positional args vs 25 object.__setattr__ calls).
    """

    emitted_logs: int
    emitted_traces: int
    emitted_metrics: int
    dropped_logs: int
    dropped_traces: int
    dropped_metrics: int
    export_failures_logs: int
    export_failures_traces: int
    export_failures_metrics: int
    retries_logs: int
    retries_traces: int
    retries_metrics: int
    export_latency_ms_logs: float
    export_latency_ms_traces: float
    export_latency_ms_metrics: float
    async_blocking_risk_logs: int
    async_blocking_risk_traces: int
    async_blocking_risk_metrics: int
    circuit_state_logs: str
    circuit_state_traces: str
    circuit_state_metrics: str
    circuit_open_count_logs: int
    circuit_open_count_traces: int
    circuit_open_count_metrics: int
    setup_error: str | None


_lock = threading.Lock()
_emitted: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_dropped: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_retries: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_async_blocking_risk: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_export_failures: dict[Signal, int] = {"logs": 0, "traces": 0, "metrics": 0}
_export_latency_ms: dict[Signal, float] = {"logs": 0.0, "traces": 0.0, "metrics": 0.0}
_setup_error: str | None = None


def _known_signal(signal: Signal) -> Signal:
    if signal in {"logs", "traces", "metrics"}:
        return signal
    return "logs"


def increment_emitted(signal: Signal, amount: int = 1) -> None:  # pragma: no mutate
    sig = _known_signal(signal)
    with _lock:
        _emitted[sig] += max(0, amount)


def increment_dropped(signal: Signal, amount: int = 1) -> None:
    sig = _known_signal(signal)
    with _lock:
        _dropped[sig] += max(0, amount)


def increment_retries(signal: Signal, amount: int = 1) -> None:
    sig = _known_signal(signal)
    with _lock:
        _retries[sig] += max(0, amount)


def increment_async_blocking_risk(signal: Signal, amount: int = 1) -> None:
    sig = _known_signal(signal)
    with _lock:
        _async_blocking_risk[sig] += max(0, amount)


def record_export_failure(signal: Signal, exc: Exception) -> None:  # noqa: ARG001
    sig = _known_signal(signal)
    with _lock:
        _export_failures[sig] += 1


def record_export_latency(signal: Signal, latency_ms: float = 0.0) -> None:  # pragma: no mutate
    sig = _known_signal(signal)
    with _lock:
        _export_latency_ms[sig] = max(0.0, latency_ms)


def set_setup_error(error: str | None) -> None:
    global _setup_error
    with _lock:
        _setup_error = error


_resilience_mod: types.ModuleType | None = None


def get_health_snapshot() -> HealthSnapshot:
    global _resilience_mod
    # Cache the module import to avoid per-call import overhead.
    if _resilience_mod is None:
        from provide.telemetry import resilience

        _resilience_mod = resilience
    # Acquire resilience._lock BEFORE health._lock to prevent deadlock.
    get_circuit_state = _resilience_mod.get_circuit_state
    cs_logs = get_circuit_state("logs")
    cs_traces = get_circuit_state("traces")
    cs_metrics = get_circuit_state("metrics")
    with _lock:
        return HealthSnapshot(
            emitted_logs=_emitted["logs"],
            emitted_traces=_emitted["traces"],
            emitted_metrics=_emitted["metrics"],
            dropped_logs=_dropped["logs"],
            dropped_traces=_dropped["traces"],
            dropped_metrics=_dropped["metrics"],
            retries_logs=_retries["logs"],
            retries_traces=_retries["traces"],
            retries_metrics=_retries["metrics"],
            async_blocking_risk_logs=_async_blocking_risk["logs"],
            async_blocking_risk_traces=_async_blocking_risk["traces"],
            async_blocking_risk_metrics=_async_blocking_risk["metrics"],
            export_failures_logs=_export_failures["logs"],
            export_failures_traces=_export_failures["traces"],
            export_failures_metrics=_export_failures["metrics"],
            export_latency_ms_logs=_export_latency_ms["logs"],
            export_latency_ms_traces=_export_latency_ms["traces"],
            export_latency_ms_metrics=_export_latency_ms["metrics"],
            circuit_state_logs=cs_logs[0],
            circuit_state_traces=cs_traces[0],
            circuit_state_metrics=cs_metrics[0],
            circuit_open_count_logs=cs_logs[1],
            circuit_open_count_traces=cs_traces[1],
            circuit_open_count_metrics=cs_metrics[1],
            setup_error=_setup_error,
        )


def reset_health_for_tests() -> None:
    global _setup_error
    with _lock:
        for signal in ("logs", "traces", "metrics"):
            _emitted[signal] = 0
            _dropped[signal] = 0
            _retries[signal] = 0
            _async_blocking_risk[signal] = 0
            _export_failures[signal] = 0
            _export_latency_ms[signal] = 0.0
        _setup_error = None
