# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Metrics provider setup."""

from __future__ import annotations

import threading
from typing import Any

from undef.telemetry import _otel
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.resilience import run_with_resilience


def _has_otel_metrics() -> bool:
    return _otel.has_otel()


_HAS_OTEL_METRICS = _has_otel_metrics()
_meter: Any | None = None
_meter_provider: Any | None = None
_meter_lock = threading.Lock()


def _load_otel_metrics_api() -> Any | None:
    if not _HAS_OTEL_METRICS:
        return None
    return _otel.load_otel_metrics_api()


def _load_otel_metrics_components() -> tuple[Any, Any, Any, Any] | None:
    if not _HAS_OTEL_METRICS:
        return None
    return _otel.load_otel_metrics_components()


def setup_metrics(config: TelemetryConfig) -> None:
    global _meter, _meter_provider
    if not config.metrics.enabled or not _HAS_OTEL_METRICS:
        return

    with _meter_lock:
        if _meter_provider is not None:
            return

    # Build exporter outside the lock to avoid blocking concurrent
    # get_meter()/shutdown_metrics() callers during slow network I/O.
    components = _load_otel_metrics_components()
    otel_metrics = _load_otel_metrics_api()
    if components is None or otel_metrics is None:
        return

    provider_cls, resource_cls, reader_cls, exporter_cls = components
    readers: list[Any] = []
    if config.metrics.otlp_endpoint:
        exporter = run_with_resilience(
            "metrics",
            lambda: exporter_cls(
                endpoint=config.metrics.otlp_endpoint,
                headers=config.metrics.otlp_headers,
                timeout=config.exporter.metrics_timeout_seconds,
            ),
        )
        if exporter is not None:
            readers.append(reader_cls(exporter))

    resource = resource_cls.create({"service.name": config.service_name, "service.version": config.version})
    provider = provider_cls(resource=resource, metric_readers=readers)

    with _meter_lock:
        if _meter_provider is not None:
            # Another thread won the race — discard ours.
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
            return
        otel_metrics.set_meter_provider(provider)
        _meter_provider = provider
        # Clear stale meters cached before provider was set up so
        # subsequent get_meter() calls return meters from the real provider.
        _meters.clear()
        _meters["undef.telemetry"] = otel_metrics.get_meter("undef.telemetry")


def get_meter(name: str | None = None) -> Any | None:
    if _meter_provider is None:
        return None
    meter_name = "undef.telemetry" if name is None else name
    with _meter_lock:
        cached = _meters.get(meter_name)
        if cached is not None:
            return cached
    otel_metrics = _load_otel_metrics_api()
    if otel_metrics is not None:
        meter_name = "undef.telemetry" if name is None else name
        return otel_metrics.get_meter(meter_name)
    return None


def _set_meter_for_test(meter: Any | None) -> None:
    global _meter, _meter_provider
    _meter = meter
    _meter_provider = None


def shutdown_metrics() -> None:
    global _meter, _meter_provider
    with _meter_lock:
        provider = _meter_provider
        if provider is None:
            return
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
        _meter = None
        _meter_provider = None
