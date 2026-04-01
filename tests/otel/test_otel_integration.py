# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Integration tests: library + real OTel SDK.

Verifies that the @trace decorator, W3C propagation, and metrics
wrappers work correctly with actual OTel providers and in-memory
exporters — not just mocks/stubs.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from provide.telemetry.backpressure import reset_queues_for_tests
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.sampling import reset_sampling_for_tests
from provide.telemetry.setup import shutdown_telemetry
from provide.telemetry.tracing.context import get_trace_context, set_trace_context
from provide.telemetry.tracing.provider import _reset_tracing_for_tests

pytestmark = pytest.mark.otel


@pytest.fixture(autouse=True)
def _clean_tracing() -> Generator[None]:
    _reset_tracing_for_tests()
    reset_sampling_for_tests()
    reset_queues_for_tests()
    set_trace_context(None, None)
    yield
    shutdown_telemetry()
    _reset_tracing_for_tests()
    set_trace_context(None, None)


# ── @trace decorator with real OTel ────────────────────────────────────


class TestTraceDecoratorWithRealOTel:
    def test_trace_decorator_creates_real_span(self) -> None:
        """@trace decorator with real OTel produces a span with valid IDs."""
        otel_trace = pytest.importorskip("opentelemetry.trace")
        sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
        sdk_resources = pytest.importorskip("opentelemetry.sdk.resources")

        from provide.telemetry.tracing import provider as pmod
        from provide.telemetry.tracing import trace

        resource = sdk_resources.Resource.create({"service.name": "test-decorator"})
        provider = sdk_trace.TracerProvider(resource=resource)
        otel_trace.set_tracer_provider(provider)
        pmod._HAS_OTEL = True
        pmod._provider_configured = True

        try:

            @trace("decorator.test.span")
            def my_operation() -> int:
                ctx = otel_trace.get_current_span().get_span_context()
                assert ctx.trace_id != 0
                assert ctx.span_id != 0
                return 42

            result = my_operation()
            assert result == 42
        finally:
            provider.shutdown()
            otel_trace.set_tracer_provider(otel_trace.NoOpTracerProvider())

    async def test_async_trace_decorator_creates_real_span(self) -> None:
        """@trace on async function with real OTel produces a span."""
        otel_trace = pytest.importorskip("opentelemetry.trace")
        sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
        sdk_resources = pytest.importorskip("opentelemetry.sdk.resources")

        from provide.telemetry.tracing import provider as pmod
        from provide.telemetry.tracing import trace

        resource = sdk_resources.Resource.create({"service.name": "test-async-decorator"})
        provider = sdk_trace.TracerProvider(resource=resource)
        otel_trace.set_tracer_provider(provider)
        pmod._HAS_OTEL = True
        pmod._provider_configured = True

        try:

            @trace("async.decorator.span")
            async def async_op() -> str:
                ctx = otel_trace.get_current_span().get_span_context()
                assert ctx.trace_id != 0
                return "async-result"

            result = await async_op()
            assert result == "async-result"
        finally:
            provider.shutdown()
            otel_trace.set_tracer_provider(otel_trace.NoOpTracerProvider())


# ── W3C propagation with real OTel ─────────────────────────────────────


class TestW3CPropagationWithRealOTel:
    def test_attach_detach_w3c_context_roundtrip(self) -> None:
        """attach_w3c_context/detach_w3c_context work with real OTel."""
        pytest.importorskip("opentelemetry.trace.propagation.tracecontext")
        pytest.importorskip("opentelemetry.context")

        from provide.telemetry._otel import attach_w3c_context, detach_w3c_context

        token = attach_w3c_context(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "congo=lZWRzIHRoZQ",
        )
        assert hasattr(token, "var")

        detach_w3c_context(token)
        # Should not raise

    def test_extract_and_bind_with_real_otel(self) -> None:
        """Full propagation cycle: extract W3C from scope, bind, verify, clear."""
        pytest.importorskip("opentelemetry.trace.propagation.tracecontext")

        from provide.telemetry.propagation import (
            bind_propagation_context,
            clear_propagation_context,
            extract_w3c_context,
        )

        scope = {
            "headers": [
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
                (b"tracestate", b"vendor=val"),
            ]
        }

        ctx = extract_w3c_context(scope)
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.span_id == "00f067aa0ba902b7"

        bind_propagation_context(ctx)
        trace_ctx = get_trace_context()
        assert trace_ctx["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert trace_ctx["span_id"] == "00f067aa0ba902b7"

        clear_propagation_context()
        assert get_trace_context() == {"trace_id": None, "span_id": None}

    def test_detach_none_token_is_noop(self) -> None:
        """Detaching None should be safe."""
        pytest.importorskip("opentelemetry.context")
        from provide.telemetry._otel import detach_w3c_context

        detach_w3c_context(None)  # Should not raise


# ── Metrics provider with real OTel ────────────────────────────────────


class TestMetricsWithRealOTel:
    def test_setup_metrics_creates_meter(self) -> None:
        """setup_metrics with real OTel creates a configured MeterProvider."""
        pytest.importorskip("opentelemetry.metrics")
        from provide.telemetry.metrics import provider as mmod

        mmod._set_meter_for_test(None)
        mmod._refresh_otel_metrics()

        cfg = TelemetryConfig.from_env({"PROVIDE_METRICS_ENABLED": "true"})
        mmod.setup_metrics(cfg)

        assert mmod._HAS_OTEL_METRICS is True

    def test_shutdown_metrics_is_safe(self) -> None:
        """Shutting down metrics when no provider is set should not crash."""
        from provide.telemetry.metrics.provider import shutdown_metrics

        shutdown_metrics()  # Should not raise


# ── Setup/shutdown lifecycle with real OTel ─────────────────────────────


class TestSetupLifecycleWithRealOTel:
    def test_full_setup_and_shutdown(self) -> None:
        """Full setup_telemetry + shutdown_telemetry cycle with real OTel."""
        pytest.importorskip("opentelemetry")
        from provide.telemetry.setup import setup_telemetry

        _reset_tracing_for_tests()
        cfg = setup_telemetry(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))
        assert cfg.tracing.enabled is True
        shutdown_telemetry()

    def test_setup_shutdown_setup_reinit_with_real_sdk(self) -> None:
        """Full setup → use → shutdown → re-setup → use cycle with real OTel SDK."""
        otel_trace = pytest.importorskip("opentelemetry.trace")
        pytest.importorskip("opentelemetry.sdk.trace")

        from provide.telemetry.metrics.provider import _set_meter_for_test
        from provide.telemetry.setup import setup_telemetry
        from provide.telemetry.tracing import provider as pmod
        from provide.telemetry.tracing import trace

        _reset_tracing_for_tests()
        _set_meter_for_test(None)

        # Cycle 1: setup, create a span, verify it works
        setup_telemetry(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))
        assert pmod._provider_configured is True

        @trace("reinit.cycle1")
        def op1() -> int:
            span = otel_trace.get_current_span()
            ctx = span.get_span_context()
            assert ctx.trace_id != 0, "cycle 1 should produce a real span"
            return 1

        assert op1() == 1
        shutdown_telemetry()
        assert pmod._provider_configured is False

        # Cycle 2: re-setup, create another span, verify it works
        _reset_tracing_for_tests()
        _set_meter_for_test(None)
        setup_telemetry(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))
        assert pmod._provider_configured is True

        @trace("reinit.cycle2")
        def op2() -> int:
            span = otel_trace.get_current_span()
            ctx = span.get_span_context()
            assert ctx.trace_id != 0, "cycle 2 should produce a real span after re-init"
            return 2

        assert op2() == 2

    def test_double_shutdown_is_safe(self) -> None:
        """Calling shutdown_telemetry twice should not raise."""
        pytest.importorskip("opentelemetry")
        shutdown_telemetry()
        shutdown_telemetry()

    def test_reconfigure_raises_after_real_otel_provider_install(self) -> None:
        pytest.importorskip("opentelemetry")
        from provide.telemetry.runtime import reconfigure_telemetry
        from provide.telemetry.setup import setup_telemetry

        _reset_tracing_for_tests()
        setup_telemetry(TelemetryConfig.from_env({"PROVIDE_TRACE_ENABLED": "true"}))
        with pytest.raises(RuntimeError, match="provider-changing reconfiguration is unsupported"):
            reconfigure_telemetry(TelemetryConfig(service_name="new-service"))


class TestOtelGuardConditions:
    """Kills mutants that flip the _HAS_OTEL / _HAS_OTEL_METRICS guard in _load_otel_*_api()."""

    def test_load_otel_trace_api_returns_module_when_otel_present(self) -> None:
        pytest.importorskip("opentelemetry.trace")
        from provide.telemetry.tracing import provider as pmod

        original = pmod._HAS_OTEL
        pmod._HAS_OTEL = True
        try:
            result = pmod._load_otel_trace_api()
            assert result is not None
            assert hasattr(result, "get_tracer")
        finally:
            pmod._HAS_OTEL = original

    def test_load_otel_metrics_api_returns_module_when_otel_present(self) -> None:
        pytest.importorskip("opentelemetry.metrics")
        from provide.telemetry.metrics import provider as mmod

        original = mmod._HAS_OTEL_METRICS
        mmod._HAS_OTEL_METRICS = True
        try:
            result = mmod._load_otel_metrics_api()
            assert result is not None
            assert hasattr(result, "get_meter")
        finally:
            mmod._HAS_OTEL_METRICS = original
