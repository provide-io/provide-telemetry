# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Shared OpenTelemetry import/loading helpers."""

from __future__ import annotations

import importlib
import logging
from typing import Any, Protocol, cast


class InstrumentationLoggingHandlerFactory(Protocol):
    def __call__(
        self,
        level: int,
        logger_provider: object | None,
        log_code_attributes: bool,
        **kwargs: object,
    ) -> logging.Handler: ...


def has_otel() -> bool:
    try:
        _import_module("opentelemetry")
        return True
    except ImportError:
        _logger.debug("opentelemetry package not installed; telemetry will use no-op fallbacks")  # pragma: no mutate
        return False


def _import_module(name: str) -> Any:
    return importlib.import_module(name)


def load_otel_trace_api() -> Any | None:
    try:
        return _import_module("opentelemetry.trace")
    except ImportError:
        _logger.debug("opentelemetry.trace not available; tracing will use no-op fallback")  # pragma: no mutate
        return None


def load_otel_tracing_components() -> tuple[Any, Any, Any, Any] | None:
    try:
        resource_mod = _import_module("opentelemetry.sdk.resources")
        trace_sdk_mod = _import_module("opentelemetry.sdk.trace")
        export_mod = _import_module("opentelemetry.sdk.trace.export")
        otlp_mod = _import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        return (
            resource_mod.Resource,
            trace_sdk_mod.TracerProvider,
            export_mod.BatchSpanProcessor,
            otlp_mod.OTLPSpanExporter,
        )
    except ImportError:
        _logger.debug("OTel tracing SDK components not available; OTLP trace export disabled")  # pragma: no mutate
        return None


def load_otel_metrics_api() -> Any | None:
    try:
        return _import_module("opentelemetry.metrics")
    except ImportError:
        _logger.debug("opentelemetry.metrics not available; metrics will use no-op fallback")  # pragma: no mutate
        return None


def load_otel_metrics_components() -> tuple[Any, Any, Any, Any] | None:
    try:
        sdk_metrics_mod = _import_module("opentelemetry.sdk.metrics")
        resources_mod = _import_module("opentelemetry.sdk.resources")
        export_mod = _import_module("opentelemetry.sdk.metrics.export")
        otlp_mod = _import_module("opentelemetry.exporter.otlp.proto.http.metric_exporter")
        return (
            sdk_metrics_mod.MeterProvider,
            resources_mod.Resource,
            export_mod.PeriodicExportingMetricReader,
            otlp_mod.OTLPMetricExporter,
        )
    except ImportError:
        _logger.debug("OTel metrics SDK components not available; OTLP metrics export disabled")  # pragma: no mutate
        return None


def load_otel_logs_components() -> tuple[Any, Any, Any, Any, Any] | None:
    try:
        logs_api_mod = _import_module("opentelemetry._logs")
        sdk_logs_mod = _import_module("opentelemetry.sdk._logs")
        sdk_logs_export_mod = _import_module("opentelemetry.sdk._logs.export")
        sdk_resources_mod = _import_module("opentelemetry.sdk.resources")
        otlp_logs_mod = _import_module("opentelemetry.exporter.otlp.proto.http._log_exporter")
        return (
            logs_api_mod,
            sdk_logs_mod,
            sdk_logs_export_mod,
            sdk_resources_mod.Resource,
            otlp_logs_mod.OTLPLogExporter,
        )
    except ImportError:
        _logger.debug("OTel logs SDK components not available; OTLP log export disabled")  # pragma: no mutate
        return None


def attach_w3c_context(traceparent: str, tracestate: str | None) -> object | None:
    """Extract W3C headers into OTEL context and attach. Returns token or None."""
    try:
        propagator_mod = _import_module("opentelemetry.trace.propagation.tracecontext")
        context_mod = _import_module("opentelemetry.context")
    except ImportError:
        _logger.debug("OTel propagation not available; W3C context attach skipped")  # pragma: no mutate
        return None
    carrier: dict[str, str] = {"traceparent": traceparent}
    if tracestate is not None:
        carrier["tracestate"] = tracestate
    propagator = propagator_mod.TraceContextTextMapPropagator()
    ctx = propagator.extract(carrier=carrier)
    token: object = context_mod.attach(ctx)
    return token


def detach_w3c_context(token: object | None) -> None:
    """Detach a previously attached OTEL context token."""
    if token is None:
        return
    try:
        context_mod = _import_module("opentelemetry.context")
    except ImportError:
        _logger.debug("OTel context not available; W3C context detach skipped")  # pragma: no mutate
        return
    context_mod.detach(token)


def load_instrumentation_logging_handler() -> InstrumentationLoggingHandlerFactory | None:
    try:
        handler_mod = _import_module("opentelemetry.instrumentation.logging.handler")
        handler_cls: object | None = getattr(handler_mod, "LoggingHandler", None)
        if handler_cls is None:
            return None
        return cast(InstrumentationLoggingHandlerFactory, handler_cls)  # pragma: no cover # pragma: no mutate
    except ImportError:
        _logger.debug("OTel instrumentation logging handler not available")  # pragma: no mutate
        return None
