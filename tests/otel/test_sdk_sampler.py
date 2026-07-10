# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""SDK-level trace sampling on the default TracerProvider."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest

from provide.telemetry.config import SamplingConfig, TelemetryConfig, TracingConfig
from provide.telemetry.setup import shutdown_telemetry
from provide.telemetry.tracing import provider as provider_mod
from provide.telemetry.tracing.provider import _reset_tracing_for_tests, setup_tracing

pytestmark = pytest.mark.otel


@pytest.fixture(autouse=True)
def _clean_tracing() -> Generator[None]:
    _reset_tracing_for_tests()
    yield
    shutdown_telemetry()
    _reset_tracing_for_tests()


def _install_memory_exporter(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Wire setup_tracing to export into an InMemorySpanExporter via SimpleSpanProcessor."""
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from provide.telemetry import _otel

    memory = InMemorySpanExporter()
    original = _otel.load_otel_tracing_components

    def _components_with_memory() -> tuple[object, object, object, object] | None:
        comps = original()
        if comps is None:
            return None
        resource_cls, provider_cls, _processor_cls, _exporter_cls = comps

        class _MemoryExporter:
            def __init__(self, **_kwargs: object) -> None:
                pass

            def export(self, spans: Any) -> Any:
                return memory.export(spans)

            def shutdown(self) -> None:
                memory.shutdown()

        return (resource_cls, provider_cls, SimpleSpanProcessor, _MemoryExporter)

    monkeypatch.setattr(_otel, "load_otel_tracing_components", _components_with_memory)
    return memory


def test_setup_tracing_sample_rate_zero_exports_no_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    """PROVIDE_TRACE_SAMPLE_RATE=0 must drop all root spans at the SDK layer."""
    pytest.importorskip("opentelemetry.sdk.trace")
    memory = _install_memory_exporter(monkeypatch)

    cfg = TelemetryConfig(
        tracing=TracingConfig(enabled=True, sample_rate=0.0, otlp_endpoint="http://127.0.0.1:4318"),
        sampling=SamplingConfig(traces_rate=1.0),
    )
    setup_tracing(cfg)

    # Use the provider we installed — do not rely on the process-global OTel
    # provider (xdist workers and prior tests may have already set it).
    assert provider_mod._provider_ref is not None
    tracer = provider_mod._provider_ref.get_tracer("test.sdk.sampler")
    for _ in range(20):
        with tracer.start_as_current_span("root.drop"):
            pass

    assert memory.get_finished_spans() == ()


def test_setup_tracing_sample_rate_one_exports_spans(monkeypatch: pytest.MonkeyPatch) -> None:
    """sample_rate=1.0 exports root spans created via the installed provider."""
    pytest.importorskip("opentelemetry.sdk.trace")
    memory = _install_memory_exporter(monkeypatch)

    cfg = TelemetryConfig(
        tracing=TracingConfig(enabled=True, sample_rate=1.0, otlp_endpoint="http://127.0.0.1:4318"),
        sampling=SamplingConfig(traces_rate=1.0),
    )
    setup_tracing(cfg)

    assert provider_mod._provider_ref is not None
    tracer = provider_mod._provider_ref.get_tracer("test.sdk.sampler")
    n = 5
    for i in range(n):
        with tracer.start_as_current_span(f"root.keep.{i}"):
            pass

    assert len(memory.get_finished_spans()) == n


def test_build_otel_trace_sampler_parent_based() -> None:
    from provide.telemetry._otel import build_otel_trace_sampler

    sampler = build_otel_trace_sampler(0.1)
    assert sampler is not None
    assert "ParentBased" in type(sampler).__name__ or "ParentBased" in repr(sampler)
