# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.tracing import provider as tracing_provider


class _FakeResource:
    @staticmethod
    def create(attrs: dict[str, object]) -> dict[str, object]:
        return attrs


class _FakeTracerProvider:
    def __init__(self, resource: object) -> None:
        self.resource = resource
        self.processors: list[object] = []

    def add_span_processor(self, processor: object) -> None:
        self.processors.append(processor)

    def shutdown(self) -> None:
        return None


class _FakeTracerApi:
    def __init__(self) -> None:
        self.provider: object | None = None
        self._baseline = object()

    def get_tracer_provider(self) -> object:
        return self._baseline

    def set_tracer_provider(self, provider: object) -> None:
        self.provider = provider


class _FakeMeterProvider:
    def __init__(self, resource: object, metric_readers: list[object]) -> None:
        self.resource = resource
        self.metric_readers = metric_readers

    def shutdown(self) -> None:
        return None


class _FakeMeterApi:
    def __init__(self) -> None:
        self.provider: object | None = None
        self._baseline = object()

    def get_meter_provider(self) -> object:
        return self._baseline

    def set_meter_provider(self, provider: object) -> None:
        self.provider = provider

    def get_meter(self, _name: str) -> object:
        return object()


def test_setup_tracing_fail_open_exporter_does_not_install_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    tracing_provider._reset_tracing_for_tests()
    fake_api = _FakeTracerApi()

    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    monkeypatch.setattr(
        tracing_provider,
        "_load_otel_tracing_components",
        lambda: (_FakeResource, _FakeTracerProvider, lambda exporter: exporter, object),
    )
    monkeypatch.setattr(tracing_provider, "_load_otel_trace_api", lambda: fake_api)
    monkeypatch.setattr("provide.telemetry.resilience.run_with_resilience", lambda _signal, _factory: None)

    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TRACE_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
        }
    )

    tracing_provider.setup_tracing(cfg)

    assert fake_api.provider is None
    assert tracing_provider._has_tracing_provider() is False


def test_setup_metrics_fail_open_exporter_does_not_install_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_provider._set_meter_for_test(None)
    fake_api = _FakeMeterApi()

    monkeypatch.setattr(metrics_provider, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(
        metrics_provider,
        "_load_otel_metrics_components",
        lambda: (_FakeMeterProvider, _FakeResource, lambda exporter: exporter, object),
    )
    monkeypatch.setattr(metrics_provider, "_load_otel_metrics_api", lambda: fake_api)
    monkeypatch.setattr("provide.telemetry.resilience.run_with_resilience", lambda _signal, _factory: None)

    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_METRICS_ENABLED": "true",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
        }
    )

    metrics_provider.setup_metrics(cfg)

    assert fake_api.provider is None
    assert metrics_provider._has_meter_provider() is False


def test_setup_tracing_fail_open_shuts_down_provider_when_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the callable(shutdown) → shutdown() branch in tracing/provider.py:146->148."""
    tracing_provider._reset_tracing_for_tests()
    fake_api = _FakeTracerApi()

    class _TrackingProvider:
        shutdown_called = False

        def __init__(self, resource: object = None) -> None:
            pass

        def add_span_processor(self, _p: object) -> None:
            pass

        def shutdown(self) -> None:
            _TrackingProvider.shutdown_called = True

    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    monkeypatch.setattr(
        tracing_provider,
        "_load_otel_tracing_components",
        lambda: (_FakeResource, _TrackingProvider, lambda exporter: exporter, object),
    )
    monkeypatch.setattr(tracing_provider, "_load_otel_trace_api", lambda: fake_api)
    monkeypatch.setattr("provide.telemetry.resilience.run_with_resilience", lambda _signal, _factory: None)

    cfg = TelemetryConfig.from_env(
        {"PROVIDE_TRACE_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}
    )
    tracing_provider.setup_tracing(cfg)
    assert _TrackingProvider.shutdown_called, "provider.shutdown() must be called on fail-open"


def test_setup_tracing_fail_open_no_shutdown_method(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the not-callable(shutdown) branch in tracing/provider.py:146->148."""
    tracing_provider._reset_tracing_for_tests()
    fake_api = _FakeTracerApi()

    class _NoShutdownProvider:
        def __init__(self, resource: object = None) -> None:
            pass

        def add_span_processor(self, _p: object) -> None:
            pass

        # No shutdown method — getattr returns None, callable(None) is False.

    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    monkeypatch.setattr(
        tracing_provider,
        "_load_otel_tracing_components",
        lambda: (_FakeResource, _NoShutdownProvider, lambda exporter: exporter, object),
    )
    monkeypatch.setattr(tracing_provider, "_load_otel_trace_api", lambda: fake_api)
    monkeypatch.setattr("provide.telemetry.resilience.run_with_resilience", lambda _signal, _factory: None)

    cfg = TelemetryConfig.from_env(
        {"PROVIDE_TRACE_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318"}
    )
    # Should not raise — gracefully skips shutdown when not callable.
    tracing_provider.setup_tracing(cfg)
    assert tracing_provider._has_tracing_provider() is False
