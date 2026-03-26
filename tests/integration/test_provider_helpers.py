# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

from types import SimpleNamespace

import pytest

from undef.telemetry import _otel
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.metrics import provider as metrics_provider
from undef.telemetry.tracing import provider as tracing_provider
from undef.telemetry.tracing.provider import _reset_tracing_for_tests

pytestmark = pytest.mark.otel


def test_metrics_has_otel_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_otel, "_import_module", lambda _: (_ for _ in ()).throw(ImportError()))
    assert metrics_provider._has_otel_metrics() is False


def test_tracing_has_otel_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_otel, "_import_module", lambda _: (_ for _ in ()).throw(ImportError()))
    assert tracing_provider._has_otel() is False


def test_metrics_has_otel_true(monkeypatch: pytest.MonkeyPatch) -> None:
    def _import_module(name: str) -> object:
        assert name == "opentelemetry"
        return object()

    monkeypatch.setattr(_otel, "_import_module", _import_module)
    assert metrics_provider._has_otel_metrics() is True


def test_tracing_has_otel_true(monkeypatch: pytest.MonkeyPatch) -> None:
    def _import_module(name: str) -> object:
        assert name == "opentelemetry"
        return object()

    monkeypatch.setattr(_otel, "_import_module", _import_module)
    assert tracing_provider._has_otel() is True


def test_metrics_load_helpers_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_provider, "_HAS_OTEL_METRICS", False)
    assert metrics_provider._load_otel_metrics_api() is None
    assert metrics_provider._load_otel_metrics_components() is None


def test_tracing_load_helpers_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", False)
    assert tracing_provider._load_otel_trace_api() is None
    assert tracing_provider._load_otel_tracing_components() is None


def test_metrics_load_helpers_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_provider, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(_otel, "_import_module", lambda _: (_ for _ in ()).throw(ImportError()))
    assert metrics_provider._load_otel_metrics_api() is None
    assert metrics_provider._load_otel_metrics_components() is None


def test_tracing_load_helpers_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    monkeypatch.setattr(_otel, "_import_module", lambda _: (_ for _ in ()).throw(ImportError()))
    assert tracing_provider._load_otel_trace_api() is None
    assert tracing_provider._load_otel_tracing_components() is None


def test_metrics_setup_with_missing_components(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics_provider._set_meter_for_test(None)
    monkeypatch.setattr(metrics_provider, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(metrics_provider, "_load_otel_metrics_api", lambda: None)
    monkeypatch.setattr(metrics_provider, "_load_otel_metrics_components", lambda: None)
    metrics_provider.setup_metrics(TelemetryConfig())
    assert metrics_provider.get_meter() is None


def test_tracing_setup_with_missing_components(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_tracing_for_tests()
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    monkeypatch.setattr(tracing_provider, "_load_otel_trace_api", lambda: None)
    monkeypatch.setattr(tracing_provider, "_load_otel_tracing_components", lambda: None)
    tracing_provider.setup_tracing(TelemetryConfig())
    assert tracing_provider._provider_configured is False


def test_metrics_load_components_success(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        "opentelemetry.sdk.metrics": SimpleNamespace(MeterProvider="mp"),
        "opentelemetry.sdk.resources": SimpleNamespace(Resource="res"),
        "opentelemetry.sdk.metrics.export": SimpleNamespace(PeriodicExportingMetricReader="reader"),
        "opentelemetry.exporter.otlp.proto.http.metric_exporter": SimpleNamespace(OTLPMetricExporter="exp"),
    }
    monkeypatch.setattr(metrics_provider, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(_otel, "_import_module", lambda name: modules[name])
    assert metrics_provider._load_otel_metrics_components() == ("mp", "res", "reader", "exp")


def test_metrics_load_api_success_imports_expected_module(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    monkeypatch.setattr(metrics_provider, "_HAS_OTEL_METRICS", True)

    def _import_module(name: str) -> object:
        assert name == "opentelemetry.metrics"
        return token

    monkeypatch.setattr(_otel, "_import_module", _import_module)
    assert metrics_provider._load_otel_metrics_api() is token


def test_tracing_load_components_success(monkeypatch: pytest.MonkeyPatch) -> None:
    modules = {
        "opentelemetry.sdk.resources": SimpleNamespace(Resource="res"),
        "opentelemetry.sdk.trace": SimpleNamespace(TracerProvider="tp"),
        "opentelemetry.sdk.trace.export": SimpleNamespace(BatchSpanProcessor="bsp"),
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": SimpleNamespace(OTLPSpanExporter="exp"),
    }
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    monkeypatch.setattr(_otel, "_import_module", lambda name: modules[name])
    assert tracing_provider._load_otel_tracing_components() == ("res", "tp", "bsp", "exp")


def test_tracing_load_api_success_imports_expected_module(monkeypatch: pytest.MonkeyPatch) -> None:
    token = object()
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)

    def _import_module(name: str) -> object:
        assert name == "opentelemetry.trace"
        return token

    monkeypatch.setattr(_otel, "_import_module", _import_module)
    assert tracing_provider._load_otel_trace_api() is token
