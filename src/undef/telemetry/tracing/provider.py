# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tracer setup and acquisition."""

from __future__ import annotations

import threading
import uuid
from contextlib import AbstractContextManager
from typing import Any, Protocol, cast

from undef.telemetry import _otel
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.tracing.context import set_trace_context


def _has_otel() -> bool:
    return _otel.has_otel()


_HAS_OTEL = _has_otel()
_provider_configured: bool = False
_provider_lock = threading.Lock()
_provider_ref: Any | None = None


class _NoopSpan(AbstractContextManager["_NoopSpan"]):
    def __init__(self, name: str) -> None:
        self.name = name
        self.trace_id = uuid.uuid4().hex
        self.span_id = uuid.uuid4().hex[:16]

    def __enter__(self) -> _NoopSpan:
        set_trace_context(self.trace_id, self.span_id)
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        set_trace_context(None, None)


class _NoopTracer:
    def start_as_current_span(self, name: str, **_: object) -> _NoopSpan:
        return _NoopSpan(name)


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

        components = _load_otel_tracing_components()
        otel_trace = _load_otel_trace_api()
        if components is None or otel_trace is None:
            return

        resource_cls, provider_cls, processor_cls, exporter_cls = components
        resource = resource_cls.create({"service.name": config.service_name, "service.version": config.version})
        provider = provider_cls(resource=resource)
        if config.tracing.otlp_endpoint:
            exporter = exporter_cls(endpoint=config.tracing.otlp_endpoint, headers=config.tracing.otlp_headers)
            provider.add_span_processor(processor_cls(exporter))
        otel_trace.set_tracer_provider(provider)
        _provider_ref = provider
        _provider_configured = True


def shutdown_tracing() -> None:
    global _provider_ref
    with _provider_lock:
        provider = _provider_ref
        if provider is None:
            return
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
        _provider_ref = None


class _TracerLike(Protocol):
    def start_as_current_span(self, name: str, **kwargs: object) -> AbstractContextManager[object]: ...


def get_tracer(name: str | None = None) -> _TracerLike:
    otel_trace = _load_otel_trace_api()
    if otel_trace is not None:
        tracer_name = "undef.telemetry" if name is None else name
        return cast(_TracerLike, otel_trace.get_tracer(tracer_name))  # pragma: no mutate
    return _NoopTracer()


tracer = get_tracer()
