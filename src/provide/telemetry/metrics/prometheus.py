# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Prometheus pull support: the reader, its status, and the Tier 2 handler.

See prometheus_metrics in spec/telemetry-api.yaml. setup_metrics() attaches a
pull reader to the provider it builds when OTEL_METRICS_EXPORTER includes
prometheus (or the listener is requested) and records here whether the
endpoint can serve. metrics_handler() and render_prometheus() then render one
collection per request, with the health snapshot as provide_telemetry_* series.
Nothing here imports OpenTelemetry: the reader base class is handed in.
"""

from __future__ import annotations

import dataclasses
import threading
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from provide.telemetry.exceptions import TelemetryError
from provide.telemetry.metrics import _prom_render as render

__all__ = ["metrics_handler", "render_prometheus"]

NOT_SET_UP = "not_set_up"
READY = "ready"
SHUT_DOWN = "shut_down"
METRICS_DISABLED = "metrics_disabled"
HOST_PROVIDER = "host_provider"
NOT_SELECTED = "not_selected"
OTEL_MISSING = "otel_missing"
SETUP_FAILED = "setup_failed"
PROCESS_LOCKED = "process_locked"

REASONS = {
    NOT_SET_UP: "provide-telemetry: metrics are not set up yet",
    SHUT_DOWN: "provide-telemetry: telemetry has been shut down",
    METRICS_DISABLED: "provide-telemetry: metrics are disabled (PROVIDE_METRICS_ENABLED=false)",
    HOST_PROVIDER: "provide-telemetry: the host application owns the MeterProvider; serve its registry instead",
    NOT_SELECTED: "provide-telemetry: the Prometheus reader is not enabled (add prometheus to OTEL_METRICS_EXPORTER)",
    OTEL_MISSING: "provide-telemetry: the OpenTelemetry SDK is not installed (install provide-telemetry[otel])",
    SETUP_FAILED: "provide-telemetry: the metrics provider failed to start",
    PROCESS_LOCKED: (
        "provide-telemetry: OpenTelemetry allows one global MeterProvider per process and an earlier setup "
        "installed it; restart the process to change the metrics setup"
    ),
}

_lock = threading.Lock()
_status = NOT_SET_UP
_serving: tuple[Any, render.RenderOptions] | None = None  # (reader, options) while READY

# The health snapshot fields served per signal, in the spec's
# prometheus_metrics.health_metrics order: (field prefix, metric, type).
_PER_SIGNAL = (
    ("emitted", "provide_telemetry_emitted_total", "counter"),
    ("dropped", "provide_telemetry_dropped_total", "counter"),
    ("export_failures", "provide_telemetry_export_failures_total", "counter"),
    ("retries", "provide_telemetry_export_retries_total", "counter"),
    ("export_latency_ms", "provide_telemetry_export_latency_milliseconds", "gauge"),
    ("async_blocking_risk", "provide_telemetry_async_blocking_risk_total", "counter"),
    ("circuit_state", "provide_telemetry_circuit_state", "gauge"),
    ("circuit_open_count", "provide_telemetry_circuit_open_total", "counter"),
)
_SIGNALS = ("logs", "traces", "metrics")
_CIRCUIT_STATES = {"closed": 0.0, "half-open": 1.0, "open": 2.0}


def set_status(status: str) -> None:
    """Record a non-ready endpoint status, forgetting any reader."""
    global _status, _serving
    with _lock:
        _status, _serving = status, None


def mark_ready(reader: Any, options: render.RenderOptions) -> None:
    """Record that reader, attached to the installed provider, can serve."""
    global _status, _serving
    with _lock:
        _status, _serving = READY, (reader, options)


def options_for(config: Any) -> render.RenderOptions:
    """The render options a config selects (scrape-time negotiation adds utf8)."""
    p = config.metrics.prometheus
    return render.RenderOptions(p.translation, scope_labels=p.scope_labels, target_info=p.target_info)


def pull_reader_class(base: Any) -> type:
    """A pull reader subclassing the SDK's MetricReader, which is passed in as base.

    collect() makes the SDK call _receive_metrics with a fresh MetricsData; the
    reader keeps the latest so snapshot() can hand it to the renderer.
    """

    class PullReader(base):  # type: ignore[misc]
        _latest: Any = None

        def _receive_metrics(self, metrics_data: Any, *args: Any, **kwargs: Any) -> None:
            del args, kwargs  # MetricReader passes a timeout this reader has no use for
            self._latest = metrics_data

        def shutdown(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs  # as above
            self._latest = None

        def snapshot(self) -> Any:
            self.collect()
            return self._latest

    return PullReader


def _circuit_value(state: str) -> float:
    return _CIRCUIT_STATES.get(state, -1.0)


def health_families(snapshot: Any) -> list[render.Family]:
    """The health snapshot as provide_telemetry_* families."""
    families = []
    for field, metric, kind in _PER_SIGNAL:
        family = render.Family(metric, kind)
        for signal in _SIGNALS:
            raw = getattr(snapshot, f"{field}_{signal}")
            value = _circuit_value(raw) if field == "circuit_state" else float(raw)
            family.samples.append(("", {"signal": signal}, value))
        families.append(family)
    setup_error = render.Family("provide_telemetry_setup_error", "gauge")
    setup_error.samples.append(("", {}, 1.0 if snapshot.setup_error else 0.0))
    receipts = render.Family("provide_telemetry_receipt_failures_total", "counter")
    receipts.samples.append(("", {}, float(snapshot.receipt_failures)))
    return [*families, setup_error, receipts]


def _current() -> tuple[Any, render.RenderOptions] | str:
    with _lock:
        return REASONS[_status] if _serving is None else _serving


def render_prometheus(accept: str | None = None) -> tuple[bytes, str]:
    """Run one collection and return (body, content_type) in the text format.

    accept is the scraper's Accept header, if any; it decides whether UTF-8
    names are allowed. Raises TelemetryError naming the reason when there is
    nothing to serve.
    """
    from provide.telemetry.health import get_health_snapshot

    current = _current()
    if isinstance(current, str):
        raise TelemetryError(current)
    reader, options = current
    utf8 = render.wants_utf8(accept)
    scrape = dataclasses.replace(options, utf8=utf8)
    families = [*render.families_from(reader.snapshot(), scrape), *health_families(get_health_snapshot())]
    content_type = render.CONTENT_TYPE_UTF8 if utf8 else render.CONTENT_TYPE_TEXT
    return render.render(families).encode(), content_type


Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


def response_for(method: str, accept: str | None) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    """(status, headers, body) for one scrape; shared by the ASGI app and the listener."""
    if method not in ("GET", "HEAD"):
        return 405, [(b"allow", b"GET, HEAD"), (b"content-type", b"text/plain; charset=utf-8")], b"method not allowed\n"
    try:
        body, content_type = render_prometheus(accept)
    except TelemetryError as exc:
        return 503, [(b"content-type", b"text/plain; charset=utf-8")], f"{exc}\n".encode()
    return 200, [(b"content-type", content_type.encode())], body if method == "GET" else b""


def metrics_handler() -> Callable[[Scope, Receive, Send], Awaitable[None]]:
    """The Tier 2 pull handler as an ASGI app; mount it wherever the host likes.

    It serves GET and HEAD, answers 405 otherwise, and 503 with a one-line
    reason until setup has attached the Prometheus reader and after shutdown.
    """

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del receive  # a scrape has no request body to read
        if scope.get("type") != "http":
            return
        raw_accept = dict(scope.get("headers") or []).get(b"accept")
        accept = str(raw_accept, errors="replace") if raw_accept else None
        status, response_headers, body = response_for(str(scope.get("method", "GET")), accept)
        await send({"type": "http.response.start", "status": status, "headers": response_headers})
        await send({"type": "http.response.body", "body": body})

    return app
