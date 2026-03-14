# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tracer setup and acquisition."""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from typing import Any, Protocol, cast

from undef.telemetry import _otel
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.resilience import run_with_resilience
from undef.telemetry.tracing.context import set_trace_context


def _has_otel() -> bool:
    return _otel.has_otel()


_HAS_OTEL = _has_otel()
_provider_configured: bool = False
_provider_lock = threading.Lock()
_provider_ref: Any | None = None


class _NoopSpan(AbstractContextManager["_NoopSpan"]):
    NOOP_TRACE_ID = "0" * 32
    NOOP_SPAN_ID = "0" * 16

    def __init__(self, name: str) -> None:
        self.name = name
        self.trace_id = self.NOOP_TRACE_ID
        self.span_id = self.NOOP_SPAN_ID

    def __enter__(self) -> _NoopSpan:
        set_trace_context(self.trace_id, self.span_id)
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        set_trace_context(None, None)


class _NoopTracer:
    def start_as_current_span(self, name: str, **_: object) -> _NoopSpan:
        return _NoopSpan(name)


def _refresh_otel_tracing() -> None:
    global _HAS_OTEL
    _HAS_OTEL = _has_otel()


def _load_otel_trace_api() -> Any | None:
    if not _HAS_OTEL:
        return None
    return _otel.load_otel_trace_api()


def _load_otel_tracing_components() -> tuple[Any, Any, Any, Any] | None:
    if not _HAS_OTEL:
        return None
    return _otel.load_otel_tracing_components()


def setup_tracing(config: TelemetryConfig) -> None:
    global _provider_configured, _provider_ref
    if not config.tracing.enabled or not _HAS_OTEL:
        return

    with _provider_lock:
        if _provider_configured:
            return

    # Build provider/exporter outside the lock to avoid blocking
    # concurrent get_tracer()/shutdown_tracing() during slow network I/O.
    components = _load_otel_tracing_components()
    otel_trace = _load_otel_trace_api()
    if components is None or otel_trace is None:
        return

    resource_cls, provider_cls, processor_cls, exporter_cls = components
    resource = resource_cls.create({"service.name": config.service_name, "service.version": config.version})
    provider = provider_cls(resource=resource)
    if config.tracing.otlp_endpoint:
        exporter = run_with_resilience(
            "traces",
            lambda: exporter_cls(
                endpoint=config.tracing.otlp_endpoint,
                headers=config.tracing.otlp_headers,
                timeout=config.exporter.traces_timeout_seconds,
            ),
        )
        if exporter is not None:
            provider.add_span_processor(processor_cls(exporter))

    with _provider_lock:
        if _provider_configured:
            # Another thread won the race — discard ours.
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
            return
        otel_trace.set_tracer_provider(provider)
        _provider_ref = provider
        _provider_configured = True


def shutdown_tracing() -> None:
    global _provider_ref, _provider_configured
    with _provider_lock:
        provider = _provider_ref
        if provider is None:
            _provider_configured = False
            return
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
        _provider_ref = None
        _provider_configured = False


def _reset_tracing_for_tests() -> None:
    global _provider_configured, _provider_ref
    _provider_configured = False
    _provider_ref = None


class _TracerLike(Protocol):
    def start_as_current_span(self, name: str, **kwargs: object) -> AbstractContextManager[object]: ...


def get_tracer(name: str | None = None) -> _TracerLike:
    if not _provider_configured:
        return _NoopTracer()
    otel_trace = _load_otel_trace_api()
    if otel_trace is not None:
        tracer_name = "undef.telemetry" if name is None else name
        return cast(_TracerLike, otel_trace.get_tracer(tracer_name))  # pragma: no mutate
    return _NoopTracer()


def _sync_otel_trace_context() -> None:
    """Sync the active OTel span's trace/span IDs into our contextvars."""
    if not _provider_configured:
        return
    otel_trace = _load_otel_trace_api()
    if otel_trace is None:
        return
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if ctx is not None and ctx.trace_id != 0 and ctx.span_id != 0:
        set_trace_context(format(ctx.trace_id, "032x"), format(ctx.span_id, "016x"))


class _LazyTracer:
    """Defers tracer resolution to call time so setup() takes effect."""

    def start_as_current_span(self, name: str, **kwargs: object) -> AbstractContextManager[object]:
        return get_tracer().start_as_current_span(name, **kwargs)


tracer: _TracerLike = _LazyTracer()
