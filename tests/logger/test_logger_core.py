# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger import bind_context, clear_context, get_context, get_logger, unbind_context
from undef.telemetry.logger import core as core_mod
from undef.telemetry.logger.core import _get_level, configure_logging
from undef.telemetry.logger.processors import (
    add_standard_fields,
    enforce_event_schema,
    merge_runtime_context,
    sanitize_sensitive_fields,
)
from undef.telemetry.schema.events import EventSchemaError


def test_get_level() -> None:
    assert _get_level("TRACE") == logging.DEBUG
    assert _get_level("INFO") == logging.INFO
    assert _get_level("WARNING") == logging.WARNING
    assert _get_level("NOT_REAL") == 20


def test_context_helpers() -> None:
    clear_context()
    bind_context(request_id="r1", session_id="s1")
    assert get_context()["request_id"] == "r1"
    unbind_context("session_id")
    assert "session_id" not in get_context()
    clear_context()
    assert get_context() == {}


def test_processors() -> None:
    cfg = TelemetryConfig(service_name="svc", environment="prod", version="2")
    event = {"event": "auth.login.success", "password": "x"}
    bind_context(request_id="req")
    merged = merge_runtime_context(None, "info", event)
    assert merged["request_id"] == "req"
    with_fields = add_standard_fields(cfg)(None, "info", merged)
    assert with_fields["service"] == "svc"
    sanitized = sanitize_sensitive_fields(True)(None, "info", with_fields)
    assert sanitized["password"] == "***"
    unsanitized = sanitize_sensitive_fields(False)(None, "info", with_fields)
    assert unsanitized["password"] == "x"
    clear_context()


def test_enforce_schema_processor() -> None:
    cfg = TelemetryConfig()
    processor = enforce_event_schema(cfg)
    processor(None, "info", {"event": "a.b.c"})
    with pytest.raises(EventSchemaError):
        processor(None, "info", {"event": "invalid"})


def test_enforce_required_keys_processor() -> None:
    cfg = TelemetryConfig.from_env({"UNDEF_TELEMETRY_REQUIRED_KEYS": "request_id"})
    processor = enforce_event_schema(cfg)
    processor(None, "info", {"event": "a.b.c", "request_id": "x"})
    with pytest.raises(EventSchemaError):
        processor(None, "info", {"event": "a.b.c"})


def test_configure_and_get_logger() -> None:
    core_mod._configured = False
    core_mod._active_config = None
    cfg = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "TRACE", "UNDEF_LOG_FORMAT": "json"})
    configure_logging(cfg)
    configure_logging(cfg)  # idempotent branch
    log = get_logger("test")
    log.trace("trace.debug.path")  # covered branch for trace at TRACE level
    bound = log.bind(component="x")
    bound.info("auth.login.success", request_id="r")


def test_trace_suppressed_when_not_trace() -> None:
    core_mod._configured = False
    core_mod._active_config = None
    cfg = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "INFO"})
    configure_logging(cfg)
    log = get_logger("test2")
    assert log.trace("auth.login.success") is None


def test_configure_logging_with_console_no_caller_timestamp() -> None:
    core_mod._configured = False
    core_mod._active_config = None
    cfg = TelemetryConfig.from_env(
        {
            "UNDEF_LOG_LEVEL": "INFO",
            "UNDEF_LOG_FORMAT": "console",
            "UNDEF_LOG_INCLUDE_TIMESTAMP": "false",
            "UNDEF_LOG_INCLUDE_CALLER": "false",
        }
    )
    configure_logging(cfg)
    get_logger("console").info("auth.login.success")


def test_get_logger_lazy_config_path() -> None:
    core_mod._configured = False
    core_mod._active_config = None
    log = core_mod.get_logger("lazy")
    log.info("auth.login.success")


def test_get_logger_default_name_and_lazy_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    core_mod._configured = False
    core_mod._active_config = None
    configured = {"count": 0}
    names: list[str] = []

    def _configure(_: TelemetryConfig) -> None:
        configured["count"] += 1
        monkeypatch.setattr(core_mod, "_configured", True)
        monkeypatch.setattr(core_mod, "_active_config", TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "TRACE"}))

    class _DummyLogger:
        def info(self, *_: object, **__: object) -> None:
            return None

    def _get_logger(name: str) -> _DummyLogger:
        names.append(name)
        return _DummyLogger()

    core_mod_any = cast(Any, core_mod)
    structlog_mod: Any = core_mod_any.structlog
    monkeypatch.setattr(core_mod, "configure_logging", _configure)
    monkeypatch.setattr(structlog_mod, "get_logger", _get_logger)
    wrapped = core_mod.get_logger()
    wrapped.info("auth.login.success")
    assert configured["count"] == 1
    assert names == ["undef"]


def test_get_logger_does_not_reconfigure_when_already_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_mod, "_configured", True)
    monkeypatch.setattr(core_mod, "_active_config", TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "INFO"}))
    configured_calls = {"count": 0}

    def _configure(_: TelemetryConfig) -> None:
        configured_calls["count"] += 1

    monkeypatch.setattr(core_mod, "configure_logging", _configure)
    log = core_mod.get_logger("named")
    log.info("auth.login.success")
    assert configured_calls["count"] == 0


def test_trace_wrapper_trace_calls_debug_only_for_trace_level() -> None:
    mock_logger = Mock()
    wrapper = core_mod._TraceWrapper(mock_logger)

    core_mod._active_config = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "TRACE"})
    wrapper.trace("evt.one", k="v")
    mock_logger.debug.assert_called_once_with("evt.one", k="v")

    mock_logger.reset_mock()
    core_mod._active_config = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "INFO"})
    wrapper.trace("evt.two")
    mock_logger.debug.assert_not_called()


def test_configure_logging_sets_expected_runtime_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    core_mod._configured = False
    core_mod._active_config = None

    basic_calls: list[dict[str, Any]] = []
    configure_calls: list[dict[str, Any]] = []
    timestamper_args: list[str | None] = []
    json_renderer_calls: list[bool] = []
    console_renderer_calls: list[bool] = []

    def _basic_config(**kwargs: Any) -> None:
        basic_calls.append(kwargs)

    class _TimeStamper:
        def __init__(self, *, fmt: str | None) -> None:
            timestamper_args.append(fmt)

    class _JSONRenderer:
        def __init__(self) -> None:
            json_renderer_calls.append(True)

    class _ConsoleRenderer:
        def __init__(self, *, colors: bool) -> None:
            self.colors = colors
            console_renderer_calls.append(colors)

    def _configure(**kwargs: Any) -> None:
        configure_calls.append(kwargs)

    core_mod_any = cast(Any, core_mod)
    logging_mod: Any = core_mod_any.logging
    structlog_mod: Any = core_mod_any.structlog
    monkeypatch.setattr(logging_mod, "basicConfig", _basic_config)
    monkeypatch.setattr(structlog_mod, "configure", _configure)
    monkeypatch.setattr(structlog_mod.processors, "TimeStamper", _TimeStamper)
    monkeypatch.setattr(structlog_mod.processors, "JSONRenderer", _JSONRenderer)
    monkeypatch.setattr(structlog_mod.dev, "ConsoleRenderer", _ConsoleRenderer)

    cfg = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "WARNING", "UNDEF_LOG_FORMAT": "json"})
    configure_logging(cfg)
    assert len(basic_calls) == 1
    assert basic_calls[0]["level"] == logging.WARNING
    assert "handlers" in basic_calls[0]
    assert len(basic_calls[0]["handlers"]) == 1
    assert basic_calls[0]["format"] == "%(message)s"
    assert basic_calls[0]["force"] is True
    assert timestamper_args == ["iso"]
    assert len(json_renderer_calls) == 1
    assert console_renderer_calls == []
    assert len(configure_calls) == 1

    processors = configure_calls[0]["processors"]
    assert isinstance(processors, list)
    assert len(processors) >= 6
    assert configure_calls[0]["cache_logger_on_first_use"] is True


def test_configure_logging_reconfigures_for_different_config(monkeypatch: pytest.MonkeyPatch) -> None:
    core_mod._configured = False
    core_mod._active_config = None
    calls = {"count": 0}

    def _basic_config(**kwargs: Any) -> None:
        _ = kwargs
        calls["count"] += 1

    core_mod_any = cast(Any, core_mod)
    logging_mod: Any = core_mod_any.logging
    monkeypatch.setattr(logging_mod, "basicConfig", _basic_config)

    cfg_a = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "INFO"})
    cfg_b = TelemetryConfig.from_env({"UNDEF_LOG_LEVEL": "ERROR"})
    configure_logging(cfg_a)
    configure_logging(cfg_b)
    assert calls["count"] == 2


def test_build_handlers_without_otel_endpoint() -> None:
    cfg = TelemetryConfig.from_env({})
    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert handlers[0].stream is not None
    assert core_mod._otel_log_provider is None


def test_has_otel_logs_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(name: str) -> object:
        _ = name
        raise ImportError

    core_mod_any = cast(Any, core_mod)
    monkeypatch.setattr(core_mod_any.importlib, "import_module", _raise)
    assert core_mod._has_otel_logs() is False


def test_has_otel_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _import(name: str) -> object:
        assert name == "opentelemetry"
        return object()

    core_mod_any = cast(Any, core_mod)
    monkeypatch.setattr(core_mod_any.importlib, "import_module", _import)
    assert core_mod._has_otel_logs() is True


def test_load_otel_logs_components_without_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_mod, "_has_otel_logs", lambda: False)
    assert core_mod._load_otel_logs_components() is None


def test_load_otel_logs_components_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_mod, "_has_otel_logs", lambda: True)

    def _raise(name: str) -> object:
        _ = name
        raise ImportError

    core_mod_any = cast(Any, core_mod)
    monkeypatch.setattr(core_mod_any.importlib, "import_module", _raise)
    assert core_mod._load_otel_logs_components() is None


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

    core_mod_any = cast(Any, core_mod)
    monkeypatch.setattr(core_mod_any.importlib, "import_module", _import)
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
        def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
            self.endpoint = endpoint
            self.headers = headers

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
    exporter = provider.processors[0].exporter
    assert isinstance(exporter, _Exporter)
    assert exporter.endpoint == "http://logs"
    assert exporter.headers == {"Authorization": "Basic abc"}
    assert core_mod._otel_log_provider is provider


def test_shutdown_logging_without_provider() -> None:
    core_mod._otel_log_provider = None
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


def test_shutdown_logging_with_missing_shutdown_attr() -> None:
    provider = object()
    core_mod._otel_log_provider = provider
    core_mod.shutdown_logging()
    assert core_mod._otel_log_provider is None
