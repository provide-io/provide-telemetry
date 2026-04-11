# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Metrics provider setup."""

from __future__ import annotations

import threading
import warnings
from typing import Any

from provide.telemetry import _otel
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.resilience import run_with_resilience


def _has_otel_metrics() -> bool:
    return _otel.has_otel()


_HAS_OTEL_METRICS = _has_otel_metrics()
_meter: Any | None = None
_meter_provider: Any | None = None
_meter_lock = threading.Lock()
_meter_global_set: bool = False  # True once we called set_meter_provider()
_setup_generation: int = 0

# Baseline captured inside setup_metrics() (not at module load) so that
# external providers installed before import are not mistaken for the default.
_baseline_meter_provider: Any | None = None
_baseline_captured: bool = False


def _load_otel_metrics_api() -> Any | None:
    if not _HAS_OTEL_METRICS:
        return None
    return _otel.load_otel_metrics_api()


def _load_otel_metrics_components() -> tuple[Any, Any, Any, Any] | None:
    if not _HAS_OTEL_METRICS:
        return None
    return _otel.load_otel_metrics_components()


def setup_metrics(config: TelemetryConfig) -> None:
    global _meter_provider, _meter_global_set
    global _baseline_meter_provider, _baseline_captured
    if not config.metrics.enabled:
        return
    from provide.telemetry.resilience import _is_running_in_event_loop

    if _is_running_in_event_loop():  # pragma: no mutate
        warnings.warn(  # pragma: no mutate
            "setup_metrics() called from an active event loop; "  # pragma: no mutate
            "provider initialization may stall the event loop. "  # pragma: no mutate
            "Call setup_telemetry() before starting the event loop.",  # pragma: no mutate
            RuntimeWarning,  # pragma: no mutate
            stacklevel=2,  # pragma: no mutate
        )  # pragma: no mutate
    if not _HAS_OTEL_METRICS:
        return

    with _meter_lock:
        if _meter_provider is not None:
            return
        # Capture the baseline provider before we install ours so that
        # _has_real_meter_provider() can distinguish external providers
        # regardless of import order.
        if not _baseline_captured:  # pragma: no mutate
            otel_metrics_api = _load_otel_metrics_api()  # pragma: no mutate
            if otel_metrics_api is not None:
                _baseline_meter_provider = otel_metrics_api.get_meter_provider()  # pragma: no mutate
            _baseline_captured = True  # pragma: no mutate
        gen = _setup_generation  # snapshot before releasing the lock

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
        _meter_global_set = True  # pragma: no mutate
        # Clear stale meters cached before provider was set up so
        # subsequent get_meter() calls return meters from the real provider.
        _meters.clear()
        _meters["provide.telemetry"] = otel_metrics.get_meter("provide.telemetry")


def _has_real_meter_provider(otel_metrics: Any) -> bool:
    """Return True if a usable (non-placeholder) OTel meter provider is globally available."""
    if _meter_provider is not None:
        return True
    if _meter_global_set:
        # We installed a provider but it was shut down; don't use the stale global.
        return False
    provider = otel_metrics.get_meter_provider()
    if not _baseline_captured:  # pragma: no mutate
        # setup_metrics() hasn't been called yet — no baseline to compare against.
        # Use class-name heuristic: the OTel API default is ProxyMeterProvider.
        return "Proxy" not in type(provider).__name__  # pragma: no mutate
    # Identity comparison against the baseline captured inside setup_metrics().
    return provider is not _baseline_meter_provider  # pragma: no mutate


def get_meter(name: str | None = None) -> Any | None:
    if _meter_provider is None:
        return None
    meter_name = "provide.telemetry" if name is None else name
    if _meter_provider is not None:
        with _meter_lock:
            cached = _meters.get(meter_name)
            if cached is not None:
                return cached
    meter = otel_metrics.get_meter(meter_name)
    if _meter_provider is not None:
        with _meter_lock:
            _meters[meter_name] = meter
    return meter


def _set_meter_for_test(meter: Any | None) -> None:
    global _meter_provider, _meter_global_set, _setup_generation
    global _baseline_meter_provider, _baseline_captured
    _meters.clear()
    if meter is not None:
        _meters["provide.telemetry"] = meter
    _meter_provider = None
    _meter_global_set = False
    _setup_generation = 0
    _baseline_meter_provider = None
    _baseline_captured = False


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
