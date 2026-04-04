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

_http_requests_total = counter("http.requests.total", "Total HTTP requests")
_http_errors_total = counter("http.errors.total", "Total HTTP errors")
_http_latency_ms = histogram("http.request.duration_ms", "HTTP request latency", "ms")
_resource_utilization = gauge("resource.utilization.percent", "Resource utilization", "%")


def record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None:
    attrs = {"route": route, "method": method, "status_code": str(status_code)}
    _http_requests_total.add(1, attrs)
    if status_code >= 500:
        _http_errors_total.add(1, attrs)
    _http_latency_ms.record(duration_ms, attrs)


def record_use_metrics(resource: str, utilization_percent: int) -> None:
    _resource_utilization.add(utilization_percent, {"resource": resource})


def classify_error(exc_name: str, status_code: int | None = None) -> dict[str, str]:
    code = status_code if status_code is not None else 0
    is_timeout = code == 0 or "timeout" in exc_name.lower()

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
