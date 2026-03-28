# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

from __future__ import annotations

import logging
import warnings
from types import SimpleNamespace
from typing import Any, cast

import pytest

from undef.telemetry import _otel
from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger import core as core_mod
from undef.telemetry.logger.core import _reset_logging_for_tests


@pytest.fixture(autouse=True)
def _bypass_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass run_with_resilience so exporter creation is direct and deterministic."""
    monkeypatch.setattr(core_mod, "run_with_resilience", lambda _sig, op: op())


def test_build_handlers_without_otel_endpoint() -> None:
    cfg = TelemetryConfig.from_env({})
    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert hasattr(handlers[0].stream, "write")
    assert core_mod._otel_log_provider is None


def test_has_otel_logs_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(name: str) -> object:
        _ = name
        raise ImportError

    monkeypatch.setattr(_otel, "_import_module", _raise)
    assert core_mod._has_otel_logs() is False


def test_has_otel_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _import(name: str) -> object:
        assert name == "opentelemetry"
        return object()

    monkeypatch.setattr(_otel, "_import_module", _import)
    assert core_mod._has_otel_logs() is True


def test_load_otel_logs_components_without_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_mod, "_has_otel_logs", lambda: False)
    assert core_mod._load_otel_logs_components() is None


def test_load_otel_logs_components_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_mod, "_has_otel_logs", lambda: True)

    def _raise(name: str) -> object:
        _ = name
        raise ImportError

    monkeypatch.setattr(_otel, "_import_module", _raise)
    assert core_mod._load_otel_logs_components() is None


def test_load_instrumentation_logging_handler_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(name: str) -> object:
        _ = name
        raise ImportError

    monkeypatch.setattr(_otel, "_import_module", _raise)
    assert core_mod._load_instrumentation_logging_handler() is None


def test_load_instrumentation_logging_handler_handles_missing_attr(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeModule:
        pass

    fake_module = _FakeModule()
    real_import = _otel._import_module

    def _import(name: str) -> object:
        if name == "opentelemetry.instrumentation.logging.handler":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(_otel, "_import_module", _import)
    assert core_mod._load_instrumentation_logging_handler() is None


def test_load_otel_logs_components_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_mod, "_has_otel_logs", lambda: True)

    logs_api_mod = object()
    sdk_logs_mod = SimpleNamespace(LoggingHandler=object())
    sdk_logs_export_mod = object()
    resource_cls = SimpleNamespace(Resource=object())
    exporter_cls = SimpleNamespace(OTLPLogExporter=object())
    mapping: dict[str, object] = {
        "opentelemetry._logs": logs_api_mod,
        "opentelemetry.sdk._logs": sdk_logs_mod,
        "opentelemetry.sdk._logs.export": sdk_logs_export_mod,
        "opentelemetry.sdk.resources": resource_cls,
        "opentelemetry.exporter.otlp.proto.http._log_exporter": exporter_cls,
    }

    def _import(name: str) -> object:
        return mapping[name]

    monkeypatch.setattr(_otel, "_import_module", _import)
    components = core_mod._load_otel_logs_components()
    assert components == (
        logs_api_mod,
        sdk_logs_mod,
        sdk_logs_export_mod,
        resource_cls.Resource,
        exporter_cls.OTLPLogExporter,
    )


def test_build_handlers_with_otel_endpoint_when_components_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs"})
    monkeypatch.setattr(core_mod, "_load_otel_logs_components", lambda: None)
    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)


def test_build_handlers_with_otel_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_TELEMETRY_SERVICE_NAME": "svc",
            "UNDEF_TELEMETRY_VERSION": "1.0.0",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "Authorization=Basic%20abc",
        }
    )

    monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

    class _Resource:
        @staticmethod
        def create(values: dict[str, str]) -> dict[str, str]:
            return values

    class _Provider:
        def __init__(self, resource: dict[str, str]) -> None:
            self.resource = resource
            self.processors: list[object] = []

        def add_log_record_processor(self, proc: object) -> None:
            self.processors.append(proc)

        def shutdown(self) -> None:
            return None

    class _Exporter:
        def __init__(self, endpoint: str, headers: dict[str, str], timeout: float) -> None:
            self.endpoint = endpoint
            self.headers = headers
            self.timeout = timeout

    class _BatchProcessor:
        def __init__(self, exporter: object) -> None:
            self.exporter = exporter

    class _LoggingHandler(logging.Handler):
        def __init__(self, level: int, logger_provider: _Provider) -> None:
            super().__init__(level=level)
            self.logger_provider = logger_provider

    calls: dict[str, object] = {}

    def _set_logger_provider(provider: _Provider) -> None:
        calls["provider"] = provider

    monkeypatch.setattr(
        core_mod,
        "_load_otel_logs_components",
        lambda: (
            SimpleNamespace(set_logger_provider=_set_logger_provider),
            SimpleNamespace(LoggerProvider=_Provider, LoggingHandler=_LoggingHandler),
            SimpleNamespace(BatchLogRecordProcessor=_BatchProcessor),
            _Resource,
            _Exporter,
        ),
    )

    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert len(handlers) == 2
    assert isinstance(handlers[0], logging.StreamHandler)
    assert isinstance(handlers[1], _LoggingHandler)
    assert handlers[1].level == logging.INFO
    provider = calls["provider"]
    assert isinstance(provider, _Provider)
    assert handlers[1].logger_provider is provider
    assert provider.resource["service.name"] == "svc"
    assert provider.resource["service.version"] == "1.0.0"
    assert len(provider.processors) == 1
    assert isinstance(provider.processors[0], _BatchProcessor)
    exporter = cast(Any, provider.processors[0]).exporter
    assert isinstance(exporter, _Exporter)
    assert exporter.endpoint == "http://logs"
    assert exporter.headers == {"Authorization": "Basic abc"}
    assert exporter.timeout == 10.0
    assert core_mod._otel_log_provider is provider


def test_build_handlers_prefers_instrumentation_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_TELEMETRY_SERVICE_NAME": "svc",
            "UNDEF_TELEMETRY_VERSION": "1.0.0",
            "UNDEF_LOG_CODE_ATTRIBUTES": "true",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
        }
    )

    class _Resource:
        @staticmethod
        def create(values: dict[str, str]) -> dict[str, str]:
            return values

    class _Provider:
        def __init__(self, resource: dict[str, str]) -> None:
            self.resource = resource
            self.processors: list[object] = []

        def add_log_record_processor(self, proc: object) -> None:
            self.processors.append(proc)

        def shutdown(self) -> None:
            return None

    class _Exporter:
        def __init__(self, endpoint: str, headers: dict[str, str], timeout: float) -> None:
            self.endpoint = endpoint
            self.headers = headers
            self.timeout = timeout

    class _BatchProcessor:
        def __init__(self, exporter: object) -> None:
            self.exporter = exporter

    class _InstrumentationHandler(logging.Handler):
        def __init__(self, level: int, logger_provider: _Provider, log_code_attributes: bool = False) -> None:
            super().__init__(level=level)
            self.logger_provider = logger_provider
            self.log_code_attributes = log_code_attributes

    calls: dict[str, object] = {}

    def _set_logger_provider(provider: _Provider) -> None:
        calls["provider"] = provider

    real_import = _otel._import_module

    def _import(name: str) -> object:
        if name == "opentelemetry.instrumentation.logging.handler":
            return SimpleNamespace(LoggingHandler=_InstrumentationHandler)
        return real_import(name)

    monkeypatch.setattr(_otel, "_import_module", _import)
    monkeypatch.setattr(
        core_mod,
        "_load_otel_logs_components",
        lambda: (
            SimpleNamespace(set_logger_provider=_set_logger_provider),
            SimpleNamespace(LoggerProvider=_Provider, LoggingHandler=object()),
            SimpleNamespace(BatchLogRecordProcessor=_BatchProcessor),
            _Resource,
            _Exporter,
        ),
    )

    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert len(handlers) == 2
    assert isinstance(handlers[1], _InstrumentationHandler)
    assert handlers[1].log_code_attributes is True
    provider = calls["provider"]
    assert handlers[1].logger_provider is provider
    assert isinstance(provider, _Provider)
    assert provider.resource["service.name"] == "svc"
    assert provider.resource["service.version"] == "1.0.0"
    exporter = cast(Any, provider.processors[0]).exporter
    assert isinstance(exporter, _Exporter)
    assert exporter.timeout == 10.0


def test_build_handlers_filters_deprecation_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_TELEMETRY_SERVICE_NAME": "svc",
            "UNDEF_TELEMETRY_VERSION": "1.0.0",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs",
        }
    )

    class _Resource:
        @staticmethod
        def create(values: dict[str, str]) -> dict[str, str]:
            return values

    class _Provider:
        def __init__(self, resource: dict[str, str]) -> None:
            self.resource = resource
            self.processors: list[object] = []

        def add_log_record_processor(self, proc: object) -> None:
            self.processors.append(proc)

    class _Exporter:
        def __init__(self, endpoint: str, headers: dict[str, str], timeout: float) -> None:
            self.endpoint = endpoint
            self.headers = headers
            self.timeout = timeout

    class _BatchProcessor:
        def __init__(self, exporter: object) -> None:
            self.exporter = exporter

    class _SDKLoggingHandler(logging.Handler):
        def __init__(self, level: int, logger_provider: _Provider) -> None:
            super().__init__(level=level)
            self.logger_provider = logger_provider

    monkeypatch.setattr(
        core_mod,
        "_load_otel_logs_components",
        lambda: (
            SimpleNamespace(set_logger_provider=lambda _: None),
            SimpleNamespace(LoggerProvider=_Provider, LoggingHandler=_SDKLoggingHandler),
            SimpleNamespace(BatchLogRecordProcessor=_BatchProcessor),
            _Resource,
            _Exporter,
        ),
    )
    monkeypatch.setattr(core_mod, "_load_instrumentation_logging_handler", lambda: None)

    filter_calls: list[tuple[str, type | None]] = []

    def _capture_filter(action: str, category: type | None = None) -> None:
        filter_calls.append((action, category))

    monkeypatch.setattr(warnings, "simplefilter", _capture_filter)

    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert len(handlers) == 2
    assert any(call == ("ignore", DeprecationWarning) for call in filter_calls)


def test_load_instrumentation_logging_handler_returns_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeHandler(logging.Handler):
        def __init__(self, level: int, **kwargs: Any) -> None:
            super().__init__(level=level)

    fake_module = SimpleNamespace(LoggingHandler=_FakeHandler)
    real_import = _otel._import_module

    def _import(name: str) -> object:
        if name == "opentelemetry.instrumentation.logging.handler":
            return fake_module
        return real_import(name)

    monkeypatch.setattr(_otel, "_import_module", _import)
    handler_cls = core_mod._load_instrumentation_logging_handler()
    assert handler_cls is _FakeHandler


def test_shutdown_logging_without_provider() -> None:
    _reset_logging_for_tests()
    core_mod.shutdown_logging()
    assert core_mod._otel_log_provider is None


def test_shutdown_logging_with_provider() -> None:
    class _Provider:
        def __init__(self) -> None:
            self.calls = 0

        def shutdown(self) -> None:
            self.calls += 1

    provider = _Provider()
    core_mod._otel_log_provider = provider
    core_mod.shutdown_logging()
    assert provider.calls == 1
    assert core_mod._otel_log_provider is None


def test_shutdown_logging_with_non_callable_shutdown_attr() -> None:
    class _Provider:
        shutdown = "not-callable"

    provider = _Provider()
    core_mod._otel_log_provider = provider
    core_mod.shutdown_logging()
    assert core_mod._otel_log_provider is None
