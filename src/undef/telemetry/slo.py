# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""SLO-oriented telemetry helpers (RED/USE baseline)."""

from __future__ import annotations

from undef.telemetry.metrics import counter, gauge, histogram

_http_requests_total = counter("http.requests.total", "Total HTTP requests")
_http_errors_total = counter("http.errors.total", "Total HTTP errors")
_http_latency_ms = histogram("http.request.duration_ms", "HTTP request latency", "ms")
_resource_utilization = gauge("resource.utilization.percent", "Resource utilization", "%")


def record_red_metrics(route: str, method: str, status_code: int, duration_ms: float) -> None:
    attrs = {"route": route, "method": method, "status_code": str(status_code)}
    _http_requests_total.add(1, attrs)
    if method != "WS" and status_code >= 500:
        _http_errors_total.add(1, attrs)
    _http_latency_ms.record(duration_ms, attrs)


def record_use_metrics(resource: str, utilization_percent: int) -> None:
    _resource_utilization.add(utilization_percent, {"resource": resource})


def classify_error(exc_name: str, status_code: int | None = None) -> dict[str, str]:
    if status_code is not None and status_code >= 500:
        return {"error_type": "server", "error_code": str(status_code), "error_name": exc_name}
    if status_code is not None and status_code >= 400:
        return {"error_type": "client", "error_code": str(status_code), "error_name": exc_name}
    return {"error_type": "internal", "error_code": "0", "error_name": exc_name}
