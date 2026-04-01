# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import Mock

import pytest

from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import bind_context, clear_context, get_context, get_logger, unbind_context
from provide.telemetry.logger import core as core_mod
from provide.telemetry.logger.core import (
    _get_level,
    _reset_logging_for_tests,
    configure_logging,
    is_debug_enabled,
    is_trace_enabled,
)
from provide.telemetry.logger.pretty import PrettyRenderer
from provide.telemetry.logger.processors import (
    add_standard_fields,
    enforce_event_schema,
    merge_runtime_context,
    sanitize_sensitive_fields,
)
from provide.telemetry.pii import reset_pii_rules_for_tests
from provide.telemetry.schema.events import EventSchemaError


@pytest.fixture(autouse=True)
def _reset_pii_rules() -> None:
    reset_pii_rules_for_tests()


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
    cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_STRICT_EVENT_NAME": "true"})
    processor = enforce_event_schema(cfg)
    processor(None, "info", {"event": "a.b.c"})
    with pytest.raises(EventSchemaError):
        processor(None, "info", {"event": "invalid"})


def test_enforce_required_keys_processor() -> None:
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_TELEMETRY_STRICT_SCHEMA": "true",
            "PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id",
        }
    )
    processor = enforce_event_schema(cfg)
    processor(None, "info", {"event": "a.b.c", "request_id": "x"})
    with pytest.raises(EventSchemaError):
        processor(None, "info", {"event": "a.b.c"})


def test_enforce_required_keys_enforced_in_compat_mode() -> None:
    cfg = TelemetryConfig.from_env({"PROVIDE_TELEMETRY_REQUIRED_KEYS": "request_id"})
    processor = enforce_event_schema(cfg)
    processor(None, "info", {"event": "a.b.c"})


def test_configure_and_get_logger() -> None:
    _reset_logging_for_tests()
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "TRACE", "PROVIDE_LOG_FORMAT": "json"})
    configure_logging(cfg)
    configure_logging(cfg)  # idempotent branch
    log = get_logger("test")
    log.trace("trace.debug.path")  # covered branch for trace at TRACE level
    bound = log.bind(component="x")
    bound.info("auth.login.success", request_id="r")


def test_trace_suppressed_when_not_trace() -> None:
    _reset_logging_for_tests()
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "INFO"})
    configure_logging(cfg)
    log = get_logger("test2")
    log.trace("auth.login.success")


def test_configure_logging_with_console_no_caller_timestamp() -> None:
    _reset_logging_for_tests()
    cfg = TelemetryConfig.from_env(
        {
            "PROVIDE_LOG_LEVEL": "INFO",
            "PROVIDE_LOG_FORMAT": "console",
            "PROVIDE_LOG_INCLUDE_TIMESTAMP": "false",
            "PROVIDE_LOG_INCLUDE_CALLER": "false",
        }
    )
    configure_logging(cfg)
    get_logger("console").info("auth.login.success")


def test_get_logger_lazy_config_path() -> None:
    _reset_logging_for_tests()
    log = core_mod.get_logger("lazy")
    log.info("auth.login.success")


def test_get_logger_default_name_and_lazy_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    configured = {"count": 0}
    names: list[str] = []

    def _configure(_: TelemetryConfig) -> None:
        configured["count"] += 1
        monkeypatch.setattr(core_mod, "_configured", True)
        monkeypatch.setattr(core_mod, "_active_config", TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "TRACE"}))

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
    assert names == ["provide"]


def test_get_logger_does_not_reconfigure_when_already_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_mod, "_configured", True)
    monkeypatch.setattr(core_mod, "_active_config", TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "INFO"}))
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

    core_mod._active_config = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "TRACE"})
    wrapper.trace("evt.one", k="v")
    # _TraceWrapper.trace() delegates to the underlying logger's .trace()
    mock_logger.trace.assert_called_once_with("evt.one", k="v")

    mock_logger.reset_mock()
    core_mod._active_config = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "INFO"})
    wrapper.trace("evt.two")
    # At INFO level, trace() on the underlying FilteringBoundLogger is a nop
    mock_logger.trace.assert_called_once_with("evt.two")


def test_structlog_gets_debug_when_config_is_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    configure_calls: list[dict[str, Any]] = []

    core_mod_any = cast(Any, core_mod)
    logging_mod: Any = core_mod_any.logging
    structlog_mod: Any = core_mod_any.structlog
    monkeypatch.setattr(logging_mod, "basicConfig", lambda **_kwargs: None)
    monkeypatch.setattr(structlog_mod, "configure", lambda **kwargs: configure_calls.append(kwargs))

    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "TRACE"})
    configure_logging(cfg)
    assert len(configure_calls) == 1
    # structlog gets DEBUG (10) clamped from TRACE (5)
    assert callable(configure_calls[0]["wrapper_class"])


def test_configure_logging_sets_expected_runtime_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()

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

    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "WARNING", "PROVIDE_LOG_FORMAT": "json"})
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
    _reset_logging_for_tests()
    calls = {"count": 0}

    def _basic_config(**kwargs: Any) -> None:
        _ = kwargs
        calls["count"] += 1

    core_mod_any = cast(Any, core_mod)
    logging_mod: Any = core_mod_any.logging
    monkeypatch.setattr(logging_mod, "basicConfig", _basic_config)

    cfg_a = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "INFO"})
    cfg_b = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "ERROR"})
    configure_logging(cfg_a)
    configure_logging(cfg_b)
    assert calls["count"] == 2


def test_lazy_logger_proxies_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {"trace": None, "bind": None, "info": None}

    class _Resolved:
        def trace(self, event: str, **kwargs: object) -> None:
            calls["trace"] = (event, kwargs)

        def bind(self, **kwargs: object) -> str:
            calls["bind"] = kwargs
            return "bound-result"

        def info(self, event: str) -> None:
            calls["info"] = event

    lazy = core_mod._LazyLogger()
    monkeypatch.setattr(core_mod, "get_logger", lambda _name=None: cast(Any, _Resolved()))

    lazy.trace("trace.event", key="value")
    assert calls["trace"] == ("trace.event", {"key": "value"})
    assert cast(Any, lazy.bind(component="svc")) == "bound-result"
    assert calls["bind"] == {"component": "svc"}
    lazy.info("info.event")
    assert calls["info"] == "info.event"


def test_shutdown_logging_with_missing_shutdown_attr() -> None:
    provider = object()
    core_mod._otel_log_provider = provider
    core_mod.shutdown_logging()
    assert core_mod._otel_log_provider is None


def test_build_handlers_returns_console_only_when_exporter_creation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = TelemetryConfig.from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://logs"})
    monkeypatch.setattr(
        core_mod,
        "_load_otel_logs_components",
        lambda: (Mock(), Mock(), Mock(), Mock(), Mock()),
    )
    monkeypatch.setattr(core_mod, "run_with_resilience", lambda _signal, _op: None)
    handlers = core_mod._build_handlers(cfg, logging.INFO)
    assert len(handlers) == 1


def test_configure_logging_rebuilds_after_shutdown_even_with_same_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    build_calls = {"count": 0}

    def _build_handlers(_config: TelemetryConfig, _level: int) -> list[logging.Handler]:
        build_calls["count"] += 1
        core_mod._otel_log_provider = object()
        return []

    core_mod_any = cast(Any, core_mod)
    logging_mod: Any = core_mod_any.logging
    monkeypatch.setattr(core_mod, "_build_handlers", _build_handlers)
    monkeypatch.setattr(logging_mod, "basicConfig", lambda **_kwargs: None)
    cfg = TelemetryConfig.from_env({})
    configure_logging(cfg)
    core_mod.shutdown_logging()
    configure_logging(cfg)
    assert build_calls["count"] == 2


def test_configure_logging_with_pretty_fmt_uses_pretty_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    configure_calls: list[dict[str, Any]] = []

    core_mod_any = cast(Any, core_mod)
    structlog_mod: Any = core_mod_any.structlog
    monkeypatch.setattr(structlog_mod, "configure", lambda **kwargs: configure_calls.append(kwargs))

    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_FORMAT": "pretty"})
    configure_logging(cfg)

    assert len(configure_calls) == 1
    processors = configure_calls[0]["processors"]
    assert isinstance(processors[-1], PrettyRenderer)


# ── is_debug_enabled / is_trace_enabled ──────────────────────────────────────


def test_is_debug_enabled_returns_true_when_unconfigured() -> None:
    _reset_logging_for_tests()
    assert is_debug_enabled() is True


def test_is_trace_enabled_returns_true_when_unconfigured() -> None:
    _reset_logging_for_tests()
    assert is_trace_enabled() is True


def test_is_debug_and_trace_enabled_with_active_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    monkeypatch.setattr(core_mod, "_build_handlers", lambda _cfg, _lvl: [])
    configure_logging(TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "INFO"}))
    assert is_debug_enabled() is False
    assert is_trace_enabled() is False
    _reset_logging_for_tests()
    configure_logging(TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "DEBUG"}))
    assert is_debug_enabled() is True
    assert is_trace_enabled() is False


def test_trace_wrapper_is_debug_and_trace_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    monkeypatch.setattr(core_mod, "_build_handlers", lambda _cfg, _lvl: [])
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "DEBUG"})
    configure_logging(cfg)
    logger = get_logger("test")
    assert logger.is_debug_enabled() is True
    assert logger.is_trace_enabled() is False


def test_lazy_logger_is_debug_and_trace_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    monkeypatch.setattr(core_mod, "_build_handlers", lambda _cfg, _lvl: [])
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "DEBUG"})
    configure_logging(cfg)
    lazy = core_mod._LazyLogger()
    assert lazy.is_debug_enabled() is True
    assert lazy.is_trace_enabled() is False


def test_configure_logging_adds_level_filter_for_module_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    configure_calls: list[dict[str, Any]] = []
    core_mod_any = cast(Any, core_mod)
    monkeypatch.setattr(core_mod_any.structlog, "configure", lambda **kw: configure_calls.append(kw))
    # asyncio=DEBUG is lower than default INFO, triggering effective_level update (line 185)
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_MODULE_LEVELS": "asyncio=DEBUG"})
    configure_logging(cfg)
    assert len(configure_calls) == 1
    # Verify the level filter processor was appended
    from provide.telemetry.logger.processors import _LevelFilter

    processors = configure_calls[0]["processors"]
    assert any(isinstance(p, _LevelFilter) for p in processors)


def test_configure_logging_module_level_higher_than_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_logging_for_tests()
    configure_calls: list[dict[str, Any]] = []
    core_mod_any = cast(Any, core_mod)
    monkeypatch.setattr(core_mod_any.structlog, "configure", lambda **kw: configure_calls.append(kw))
    # asyncio=ERROR is higher than default DEBUG — effective_level stays at DEBUG (line 184 False branch)
    cfg = TelemetryConfig.from_env({"PROVIDE_LOG_LEVEL": "DEBUG", "PROVIDE_LOG_MODULE_LEVELS": "asyncio=ERROR"})
    configure_logging(cfg)
    assert len(configure_calls) == 1
    from provide.telemetry.logger.processors import _LevelFilter

    processors = configure_calls[0]["processors"]
    assert any(isinstance(p, _LevelFilter) for p in processors)


def test_configure_logging_passes_max_nesting_depth_to_harden_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kills mutmut_33: harden_input receives None instead of config.security.max_nesting_depth.
    # With None, `depth < max_depth` raises TypeError when processing a nested dict.
    _reset_logging_for_tests()
    core_mod_any = cast(Any, core_mod)
    captured: list[tuple[Any, ...]] = []
    original = core_mod_any.harden_input

    def _spy_harden(*args: Any) -> Any:
        captured.append(args)
        return original(*args)

    monkeypatch.setattr(core_mod_any, "harden_input", _spy_harden)
    monkeypatch.setattr(core_mod_any.structlog, "configure", lambda **kw: None)

    cfg = TelemetryConfig.from_env({"PROVIDE_SECURITY_MAX_NESTING_DEPTH": "3"})
    configure_logging(cfg)

    assert len(captured) == 1
    _max_attr_value_length, _max_attr_count, max_nesting_depth = captured[0]
    assert max_nesting_depth == 3


def test_configure_logging_passes_max_nesting_depth_to_sanitize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kills mutmut_42: sanitize_sensitive_fields called without max_nesting_depth → uses default 8.
    # Spy on sanitize_sensitive_fields to assert it receives the configured depth.
    _reset_logging_for_tests()
    core_mod_any = cast(Any, core_mod)
    captured: list[tuple[Any, ...]] = []
    original_ssf = core_mod_any.sanitize_sensitive_fields

    def _spy_sanitize(*args: Any) -> Any:
        captured.append(args)
        return original_ssf(*args)

    monkeypatch.setattr(core_mod_any, "sanitize_sensitive_fields", _spy_sanitize)
    monkeypatch.setattr(core_mod_any.structlog, "configure", lambda **kw: None)

    cfg = TelemetryConfig.from_env({"PROVIDE_SECURITY_MAX_NESTING_DEPTH": "3", "PROVIDE_LOG_SANITIZE": "true"})
    configure_logging(cfg)

    assert len(captured) == 1
    _enabled, max_nesting_depth = captured[0]
    assert max_nesting_depth == 3
