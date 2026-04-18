# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import core as logger_core
from provide.telemetry.metrics import provider as metrics_provider
from provide.telemetry.setup import _reset_all_for_tests, setup_telemetry, shutdown_telemetry
from provide.telemetry.tracing import provider as tracing_provider

pytestmark = pytest.mark.integration


class _FakeResource:
    @staticmethod
    def create(attrs: dict[str, str]) -> dict[str, str]:
        return attrs


class _FakeLogExporter:
    def __init__(self, *, endpoint: str, headers: dict[str, str], timeout: float) -> None:
        self.endpoint = endpoint
        self.headers = headers
        self.timeout = timeout


class _FakeLogRecordProcessor:
    def __init__(self, exporter: _FakeLogExporter) -> None:
        self.exporter = exporter


class _FakeLogProvider:
    def __init__(self, *, resource: dict[str, str]) -> None:
        self.resource = resource
        self.processors: list[object] = []
        self.shutdown_calls = 0

    def add_log_record_processor(self, processor: object) -> None:
        self.processors.append(processor)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeLoggingHandler(logging.Handler):
    def __init__(self, *, level: int, logger_provider: _FakeLogProvider) -> None:
        super().__init__(level=level)
        self.logger_provider = logger_provider

    def emit(self, record: logging.LogRecord) -> None:
        _ = record


class _FakeSpanExporter:
    def __init__(self, *, endpoint: str, headers: dict[str, str], timeout: float) -> None:
        self.endpoint = endpoint
        self.headers = headers
        self.timeout = timeout


class _FakeSpanProcessor:
    def __init__(self, exporter: _FakeSpanExporter) -> None:
        self.exporter = exporter


class _FakeTracerProvider:
    def __init__(self, *, resource: dict[str, str]) -> None:
        self.resource = resource
        self.processors: list[object] = []
        self.shutdown_calls = 0

    def add_span_processor(self, processor: object) -> None:
        self.processors.append(processor)

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeMetricExporter:
    def __init__(self, *, endpoint: str, headers: dict[str, str], timeout: float) -> None:
        self.endpoint = endpoint
        self.headers = headers
        self.timeout = timeout


class _FakeMetricReader:
    def __init__(self, exporter: _FakeMetricExporter) -> None:
        self.exporter = exporter


class _FakeMeterProvider:
    def __init__(self, *, resource: dict[str, str], metric_readers: list[object]) -> None:
        self.resource = resource
        self.metric_readers = metric_readers
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


@pytest.mark.otel
def test_setup_then_shutdown_then_setup_reinitializes_otel_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_all_for_tests()

    logs_api_mod = SimpleNamespace(set_logger_provider=lambda _provider: None)
    sdk_logs_mod = SimpleNamespace(LoggerProvider=_FakeLogProvider, LoggingHandler=_FakeLoggingHandler)
    sdk_logs_export_mod = SimpleNamespace(BatchLogRecordProcessor=_FakeLogRecordProcessor)
    otel_trace_api = SimpleNamespace(set_tracer_provider=lambda _provider: None, get_tracer_provider=lambda: None)
    otel_metrics_api = SimpleNamespace(
        set_meter_provider=lambda _provider: None,
        get_meter_provider=lambda: None,
        get_meter=lambda _name: object(),
    )

    monkeypatch.setattr(logger_core, "_has_otel_logs", lambda: True)
    monkeypatch.setattr(
        logger_core,
        "_load_otel_logs_components",
        lambda: (logs_api_mod, sdk_logs_mod, sdk_logs_export_mod, _FakeResource, _FakeLogExporter),
    )
    monkeypatch.setattr(logger_core, "_load_instrumentation_logging_handler", lambda: None)
    monkeypatch.setattr(tracing_provider, "_HAS_OTEL", True)
    monkeypatch.setattr(tracing_provider, "_has_otel", lambda: True)
    monkeypatch.setattr(tracing_provider, "_load_otel_trace_api", lambda: otel_trace_api)
    monkeypatch.setattr(
        tracing_provider,
        "_load_otel_tracing_components",
        lambda: (_FakeResource, _FakeTracerProvider, _FakeSpanProcessor, _FakeSpanExporter),
    )
    monkeypatch.setattr(metrics_provider, "_HAS_OTEL_METRICS", True)
    monkeypatch.setattr(metrics_provider, "_has_otel_metrics", lambda: True)
    monkeypatch.setattr(metrics_provider, "_load_otel_metrics_api", lambda: otel_metrics_api)
    monkeypatch.setattr(
        metrics_provider,
        "_load_otel_metrics_components",
        lambda: (_FakeMeterProvider, _FakeResource, _FakeMetricReader, _FakeMetricExporter),
    )

    cfg = TelemetryConfig.from_env(
        {
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://traces",
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT": "http://metrics",
        }
    )
    setup_telemetry(cfg)
    first_log_provider = logger_core._otel_log_provider
    first_trace_provider = tracing_provider._provider_ref
    first_meter_provider = metrics_provider._meter_provider
    assert isinstance(first_log_provider, _FakeLogProvider)
    assert isinstance(first_trace_provider, _FakeTracerProvider)
    assert isinstance(first_meter_provider, _FakeMeterProvider)

    shutdown_telemetry()
    assert logger_core._otel_log_provider is None
    assert tracing_provider._provider_ref is None
    assert tracing_provider._provider_configured is False
    assert metrics_provider._meter_provider is None

    setup_telemetry(cfg)
    assert isinstance(logger_core._otel_log_provider, _FakeLogProvider)
    assert isinstance(tracing_provider._provider_ref, _FakeTracerProvider)
    assert tracing_provider._provider_configured is True
    assert isinstance(metrics_provider._meter_provider, _FakeMeterProvider)
    assert logger_core._otel_log_provider is not first_log_provider
    assert tracing_provider._provider_ref is not first_trace_provider
    assert metrics_provider._meter_provider is not first_meter_provider

    shutdown_telemetry()
