# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""SLO-oriented telemetry helpers (RED/USE baseline)."""

from __future__ import annotations

__all__ = [
    "classify_error",
    "record_red_metrics",
    "record_use_metrics",
]

import threading

from provide.telemetry.metrics import counter, gauge, histogram
from provide.telemetry.metrics.instruments import Counter, Gauge, Histogram

_lock = threading.Lock()
_counters: dict[str, Counter] = {}
_histograms: dict[str, Histogram] = {}
_gauges: dict[str, Gauge] = {}


def _rebind_slo_instruments() -> None:
    """Clear cached instruments so they rebind to current providers on next use."""
    with _lock:
        _counters.clear()
        _histograms.clear()
        _gauges.clear()


def _lazy_counter(name: str, description: str) -> Counter:
    with _lock:
        if name not in _counters:
            _counters[name] = counter(name, description)
        return _counters[name]


def _lazy_histogram(name: str, description: str, unit: str) -> Histogram:
    with _lock:
        if name not in _histograms:
            _histograms[name] = histogram(name, description, unit)
        return _histograms[name]


def _lazy_gauge(name: str, description: str, unit: str) -> Gauge:
    with _lock:
        if name not in _gauges:
            _gauges[name] = gauge(name, description, unit)
        return _gauges[name]


def record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None:
    attrs = {"route": route, "method": method, "status_code": str(status_code)}
    _lazy_counter("http.requests.total", "Total HTTP requests").add(1, attrs)
    if method != "WS" and status_code >= 500:
        _lazy_counter("http.errors.total", "Total HTTP errors").add(1, attrs)
    _lazy_histogram("http.request.duration_ms", "HTTP request latency", "ms").record(duration_ms, attrs)


def record_use_metrics(resource: str, utilization_percent: int) -> None:
    _lazy_gauge("resource.utilization.percent", "Resource utilization", "%").set(
        utilization_percent, {"resource": resource}
    )


def classify_error(exc_name: str, status_code: int | None = None) -> dict[str, str]:
    code = status_code if status_code is not None else 0
    is_timeout = "timeout" in exc_name.lower() or code in (408, 504)

    if is_timeout:
        category = "timeout"
        severity = "info"
        error_type = "internal"
    elif code >= 500:
        category = "server_error"
        severity = "critical"
        error_type = "server"
    elif code >= 400:
        category = "client_error"
        severity = "critical" if code == 429 else "warning"
        error_type = "client"
    else:
        category = "unclassified"
        severity = "info"
        error_type = "internal"

    return {
        # Legacy keys (used by processors and existing consumers)
        "error_type": error_type,
        "error_code": str(code),
        "error_name": exc_name,
        # Spec-aligned keys (cross-language parity)
        "error.type": exc_name,
        "error.category": category,
        "error.severity": severity,
        "http.status_code": str(code),
    }


def _reset_slo_for_tests() -> None:
    with _lock:
        _counters.clear()
        _histograms.clear()
        _gauges.clear()
