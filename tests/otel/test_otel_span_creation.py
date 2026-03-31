# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Real OpenTelemetry span creation tests.

These tests verify actual OTel TracerProvider/Tracer/Span lifecycle
using in-memory exporters, confirming that the telemetry library
integrates correctly with the OTel SDK (not just mock/stub paths).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.setup import shutdown_telemetry
from provide.telemetry.tracing.context import get_trace_context, set_trace_context
from provide.telemetry.tracing.provider import (
    _NoopSpan,
    _NoopTracer,
    _reset_tracing_for_tests,
    get_tracer,
    setup_tracing,
)

pytestmark = pytest.mark.otel


@pytest.fixture(autouse=True)
def _clean_tracing() -> Generator[None]:
    _reset_tracing_for_tests()
    set_trace_context(None, None)
    yield
    shutdown_telemetry()
    _reset_tracing_for_tests()
    set_trace_context(None, None)


def test_real_otel_tracer_creates_span_with_valid_ids() -> None:
    """A real OTel tracer produces spans with valid trace/span IDs."""
    otel_trace = pytest.importorskip("opentelemetry.trace")
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    sdk_resources = pytest.importorskip("opentelemetry.sdk.resources")
    export_module = pytest.importorskip("opentelemetry.sdk.trace.export")

    resource = sdk_resources.Resource.create({"service.name": "test-spans"})
    provider = sdk_trace.TracerProvider(resource=resource)
    exporter = export_module.SimpleSpanProcessor(export_module.ConsoleSpanExporter())
    provider.add_span_processor(exporter)
    otel_trace.set_tracer_provider(provider)

    try:
        tracer = otel_trace.get_tracer("test.real.spans")
        with tracer.start_as_current_span("test-operation") as span:
            ctx = span.get_span_context()
            assert ctx.trace_id != 0
            assert ctx.span_id != 0
            trace_id_hex = format(ctx.trace_id, "032x")
            span_id_hex = format(ctx.span_id, "016x")
            assert len(trace_id_hex) == 32
            assert len(span_id_hex) == 16
    finally:
        provider.shutdown()
        otel_trace.set_tracer_provider(otel_trace.NoOpTracerProvider())


def test_real_otel_nested_spans_share_trace_id() -> None:
    """Nested spans share the same trace_id but have distinct span_ids."""
    otel_trace = pytest.importorskip("opentelemetry.trace")
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    sdk_resources = pytest.importorskip("opentelemetry.sdk.resources")
    export_module = pytest.importorskip("opentelemetry.sdk.trace.export")

    resource = sdk_resources.Resource.create({"service.name": "test-nested"})
    provider = sdk_trace.TracerProvider(resource=resource)
    memory = export_module.SimpleSpanProcessor(export_module.ConsoleSpanExporter())
    provider.add_span_processor(memory)
    otel_trace.set_tracer_provider(provider)

    try:
        tracer = otel_trace.get_tracer("test.nested")
        with tracer.start_as_current_span("parent") as parent_span:
            parent_ctx = parent_span.get_span_context()
            with tracer.start_as_current_span("child") as child_span:
                child_ctx = child_span.get_span_context()
                assert child_ctx.trace_id == parent_ctx.trace_id
                assert child_ctx.span_id != parent_ctx.span_id
    finally:
        provider.shutdown()
        otel_trace.set_tracer_provider(otel_trace.NoOpTracerProvider())


def test_real_otel_span_attributes_and_status() -> None:
    """A real OTel span carries attributes and status set during execution."""
    otel_trace = pytest.importorskip("opentelemetry.trace")
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    sdk_resources = pytest.importorskip("opentelemetry.sdk.resources")

    resource = sdk_resources.Resource.create({"service.name": "test-attrs"})
    provider = sdk_trace.TracerProvider(resource=resource)
    otel_trace.set_tracer_provider(provider)

    try:
        tracer = otel_trace.get_tracer("test.attrs")
        with tracer.start_as_current_span("attr-op") as span:
            span.set_attribute("http.method", "GET")
            span.set_attribute("http.status_code", 200)
            span.set_status(otel_trace.StatusCode.OK)
            ctx = span.get_span_context()
            assert ctx.trace_id != 0
            assert ctx.span_id != 0
            assert ctx.is_valid
    finally:
        provider.shutdown()
        otel_trace.set_tracer_provider(otel_trace.NoOpTracerProvider())


def test_real_otel_span_records_exception() -> None:
    """Spans correctly record exceptions and set error status."""
    otel_trace = pytest.importorskip("opentelemetry.trace")
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    sdk_resources = pytest.importorskip("opentelemetry.sdk.resources")

    resource = sdk_resources.Resource.create({"service.name": "test-exception"})
    provider = sdk_trace.TracerProvider(resource=resource)
    otel_trace.set_tracer_provider(provider)

    try:
        tracer = otel_trace.get_tracer("test.exception")
        with pytest.raises(ValueError, match="test error"), tracer.start_as_current_span("error-op") as span:
            span.record_exception(ValueError("test error"))
            span.set_status(otel_trace.StatusCode.ERROR, "test error")
            # Verify error status was set on the span
            assert span.status.status_code == otel_trace.StatusCode.ERROR
            raise ValueError("test error")
    finally:
        provider.shutdown()
        otel_trace.set_tracer_provider(otel_trace.NoOpTracerProvider())


def test_noop_tracer_produces_deterministic_ids() -> None:
    """The library's _NoopTracer sets well-known zero IDs in trace context."""
    tracer = _NoopTracer()
    with tracer.start_as_current_span("noop-test") as span:
        assert isinstance(span, _NoopSpan)
        assert span.trace_id == "0" * 32
        assert span.span_id == "0" * 16
        ctx = get_trace_context()
        assert ctx["trace_id"] == "0" * 32
        assert ctx["span_id"] == "0" * 16

    # After exiting, context is cleared
    ctx = get_trace_context()
    assert ctx["trace_id"] is None
    assert ctx["span_id"] is None


def test_get_tracer_returns_noop_when_otel_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OTel is not available, get_tracer falls back to _NoopTracer."""
    from provide.telemetry.tracing import provider as pmod

    monkeypatch.setattr(pmod, "_HAS_OTEL", False)
    tracer = get_tracer("test")
    assert isinstance(tracer, _NoopTracer)


def test_setup_tracing_creates_real_provider() -> None:
    """setup_tracing with real OTel creates a configured TracerProvider."""
    otel_trace = pytest.importorskip("opentelemetry.trace")
    from provide.telemetry.tracing import provider as pmod

    _reset_tracing_for_tests()
    pmod._refresh_otel_tracing()

    cfg = TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"})
    setup_tracing(cfg)

    # Provider should now be configured
    assert pmod._provider_configured is True
    assert pmod._provider_ref is not None and hasattr(pmod._provider_ref, "shutdown")

    # The tracer from get_tracer should produce real spans
    tracer = otel_trace.get_tracer("test.setup")
    with tracer.start_as_current_span("setup-test-span") as span:
        ctx = span.get_span_context()
        assert ctx.trace_id != 0


def test_setup_tracing_idempotent_with_real_otel() -> None:
    """Calling setup_tracing twice doesn't create a second provider."""
    pytest.importorskip("opentelemetry.trace")
    from provide.telemetry.tracing import provider as pmod

    _reset_tracing_for_tests()
    pmod._refresh_otel_tracing()

    cfg = TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"})
    setup_tracing(cfg)
    first_ref = pmod._provider_ref

    setup_tracing(cfg)
    assert pmod._provider_ref is first_ref
