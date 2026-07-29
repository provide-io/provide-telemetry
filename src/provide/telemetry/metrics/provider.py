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
from provide.telemetry._endpoint import validate_otlp_endpoint
from provide.telemetry._resource import build_resource
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.resilience import run_with_resilience
from provide.telemetry.resilient_exporter import wrap_exporter


def _has_otel_metrics() -> bool:
    return _otel.has_otel()


_HAS_OTEL_METRICS = _has_otel_metrics()
_meters: dict[str, Any] = {}
_meter_provider: Any | None = None
_meter_lock = threading.Lock()
_meter_global_set: bool = False  # True once we called set_meter_provider()
_setup_generation: int = 0
_metrics_explicitly_disabled: bool = False


def _load_otel_metrics_api() -> Any | None:
    if not _HAS_OTEL_METRICS:
        return None
    return _otel.load_otel_metrics_api()


def _load_otel_metrics_components() -> tuple[Any, Any, Any, Any] | None:
    if not _HAS_OTEL_METRICS:
        return None
    return _otel.load_otel_metrics_components()


def _refresh_otel_metrics() -> None:
    global _HAS_OTEL_METRICS
    _HAS_OTEL_METRICS = _has_otel_metrics()


def _has_meter_provider() -> bool:
    """Return True if a meter provider is installed or was ever installed (thread-safe)."""
    with _meter_lock:
        return _meter_provider is not None or _meter_global_set


def _has_live_meter_provider() -> bool:
    """Return True if a live meter provider is currently installed."""
    with _meter_lock:
        return _meter_provider is not None


def _has_effective_meter_provider() -> bool:
    """Return True if an instrument created now would reach a real meter provider.

    Distinct from :func:`_has_live_meter_provider`, which answers "did *we*
    install one" — the question reconfiguration safety turns on. This answers
    "is one in play", which includes a provider a host application installed
    itself: such a provider owns the OTel global, so ``get_meter()`` resolves it
    and measurements are recorded through it.

    Delegates to the same predicate ``get_meter()`` gates on, so runtime status
    and the meter can never disagree about which provider is in play.
    """
    if _has_live_meter_provider():
        return True
    otel_metrics = _load_otel_metrics_api()
    if otel_metrics is None:
        return False
    with _meter_lock:
        return _has_real_meter_provider(otel_metrics)


def setup_metrics(config: TelemetryConfig) -> None:
    global _meter_provider, _meter_global_set
    global _metrics_explicitly_disabled
    if not config.metrics.enabled:
        _metrics_explicitly_disabled = True
        return
    _metrics_explicitly_disabled = False
    from provide.telemetry.resilience import _is_running_in_event_loop

    if (
        _is_running_in_event_loop()
    ):  # pragma: no mutate — event-loop guard; both branches exercised by asyncio-specific tests
        warnings.warn(  # pragma: no mutate — best-effort warning emission; exact wording is non-semantic
            "setup_metrics() called from an active event loop; "  # pragma: no mutate — warning message string is non-semantic
            "provider initialization may stall the event loop. "  # pragma: no mutate — warning message string is non-semantic
            "Call setup_telemetry() before starting the event loop.",  # pragma: no mutate — warning message string is non-semantic
            RuntimeWarning,  # pragma: no mutate — warning category; any subclass of Warning is equivalent for the catch-all tests
            stacklevel=2,  # pragma: no mutate — stacklevel tuning; any small positive int surfaces the caller frame
        )  # pragma: no mutate — closing paren line for multi-line call; trivial
    if not _HAS_OTEL_METRICS:
        return

    with _meter_lock:
        if _meter_provider is not None:
            return
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
        raw_exporter = run_with_resilience(
            "metrics",
            lambda: exporter_cls(
                endpoint=validate_otlp_endpoint(config.metrics.otlp_endpoint),
                headers=config.metrics.otlp_headers,
                timeout=config.exporter.metrics_timeout_seconds,
            ),
        )
        if raw_exporter is None:
            return
        # Wrap so every export() call applies retry/timeout/circuit-breaker policy.
        readers.append(reader_cls(wrap_exporter("metrics", raw_exporter)))

    resource = build_resource(config, resource_cls)
    provider = provider_cls(resource=resource, metric_readers=readers)

    with _meter_lock:
        if _meter_provider is not None or _setup_generation != gen:
            # Another thread won the race OR shutdown happened mid-build — discard ours.
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
            return
        otel_metrics.set_meter_provider(provider)
        _meter_provider = provider
        _meter_global_set = True  # pragma: no mutate — latched True after successful provider install; boolean toggle asserted by shutdown tests
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
    # Whatever owns the global now — ours is gone, so a live provider here is a
    # host application's, whether it was installed before or after our setup.
    return _otel.is_live_provider(
        otel_metrics.get_meter_provider()
    )  # pragma: no mutate — identity check against captured baseline; asserted by provider-swap tests


def get_meter(name: str | None = None) -> Any | None:
    if _metrics_explicitly_disabled:
        return None
    otel_metrics = _load_otel_metrics_api()
    if otel_metrics is None:
        return None
    if not _has_real_meter_provider(otel_metrics):
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
    global _metrics_explicitly_disabled
    _meters.clear()
    if meter is not None:
        _meters["provide.telemetry"] = meter
    _meter_provider = None
    _meter_global_set = False
    _setup_generation = 0
    _metrics_explicitly_disabled = False


def shutdown_metrics() -> None:
    global _meter_provider, _setup_generation
    with _meter_lock:
        _setup_generation += 1
        provider = _meter_provider
        if provider is None:
            return
        try:
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
        finally:
            _meters.clear()
            _meter_provider = None
