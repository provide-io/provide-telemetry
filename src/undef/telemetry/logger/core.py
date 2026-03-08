# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 MindTenet LLC
# This file is part of Undef Telemetry.
"""Logging setup and accessors."""

from __future__ import annotations

import importlib
import logging
import sys
import threading
from typing import Any

import structlog

from undef.telemetry.config import TelemetryConfig
from undef.telemetry.logger.processors import (
    add_standard_fields,
    enforce_event_schema,
    merge_runtime_context,
    sanitize_sensitive_fields,
)

TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _get_level(level: str) -> int:
    if level == "TRACE":
        return logging.DEBUG
    mapped = logging.getLevelName(level)
    if isinstance(mapped, int):
        return mapped
    return logging.INFO


_configured = False
_lock = threading.Lock()
_active_config: TelemetryConfig | None = None
_otel_log_provider: Any | None = None


def _has_otel_logs() -> bool:
    try:
        importlib.import_module("opentelemetry")
        return True
    except ImportError:
        return False


def _load_otel_logs_components() -> tuple[Any, Any, Any, Any, Any] | None:
    if not _has_otel_logs():
        return None
    try:
        logs_api_mod = importlib.import_module("opentelemetry._logs")
        sdk_logs_mod = importlib.import_module("opentelemetry.sdk._logs")
        sdk_logs_export_mod = importlib.import_module("opentelemetry.sdk._logs.export")
        sdk_resources_mod = importlib.import_module("opentelemetry.sdk.resources")
        otlp_logs_mod = importlib.import_module("opentelemetry.exporter.otlp.proto.http._log_exporter")
        return (
            logs_api_mod,
            sdk_logs_mod,
            sdk_logs_export_mod,
            sdk_resources_mod.Resource,
            otlp_logs_mod.OTLPLogExporter,
        )
    except ImportError:
        return None


def _build_handlers(config: TelemetryConfig, level: int) -> list[logging.Handler]:
    global _otel_log_provider
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]  # pragma: no mutate
    _otel_log_provider = None

    if not config.logging.otlp_endpoint:
        return handlers

    components = _load_otel_logs_components()
    if components is None:
        return handlers

    logs_api_mod, sdk_logs_mod, sdk_logs_export_mod, resource_cls, otlp_exporter_cls = components
    resource = resource_cls.create({"service.name": config.service_name, "service.version": config.version})
    provider = sdk_logs_mod.LoggerProvider(resource=resource)
    exporter = otlp_exporter_cls(endpoint=config.logging.otlp_endpoint, headers=config.logging.otlp_headers)
    provider.add_log_record_processor(sdk_logs_export_mod.BatchLogRecordProcessor(exporter))
    logs_api_mod.set_logger_provider(provider)
    handlers.append(sdk_logs_mod.LoggingHandler(level=level, logger_provider=provider))
    _otel_log_provider = provider
    return handlers


def configure_logging(config: TelemetryConfig) -> None:
    global _configured, _active_config
    with _lock:
        if _configured and _active_config == config:
            return

        level = _get_level(config.logging.level)
        handlers = _build_handlers(config, level)
        logging.basicConfig(level=level, handlers=handlers, format="%(message)s", force=True)

        processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            merge_runtime_context,
            structlog.processors.add_log_level,
        ]
        if config.logging.include_timestamp:
            processors.append(structlog.processors.TimeStamper(fmt="iso"))

        processors.extend(
            [
                add_standard_fields(config),
                enforce_event_schema(config),
                sanitize_sensitive_fields(config.logging.sanitize),
            ]
        )

        if config.logging.include_caller:
            processors.append(
                structlog.processors.CallsiteParameterAdder(
                    parameters=[
                        structlog.processors.CallsiteParameter.FILENAME,
                        structlog.processors.CallsiteParameter.LINENO,
                    ]
                )
            )

        renderer: Any
        if config.logging.fmt == "json":
            renderer = structlog.processors.JSONRenderer()
        else:
            renderer = structlog.dev.ConsoleRenderer(colors=False)

        processors.append(renderer)

        structlog.configure(
            processors=processors,
            wrapper_class=structlog.make_filtering_bound_logger(level),
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        _active_config = config
        _configured = True


def shutdown_logging() -> None:
    global _otel_log_provider
    with _lock:
        provider = _otel_log_provider
        if provider is None:
            return
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
        _otel_log_provider = None


def get_logger(name: str | None = None) -> Any:
    if not _configured:
        from undef.telemetry.config import TelemetryConfig

        configure_logging(TelemetryConfig.from_env())
    return _TraceWrapper(structlog.get_logger(name or "undef"))


class _TraceWrapper:
    def __init__(self, logger: Any) -> None:
        self._logger = logger

    def __getattr__(self, item: str) -> Any:
        return getattr(self._logger, item)

    def trace(self, event: str, **kwargs: Any) -> None:
        if _active_config is not None and _active_config.logging.level == "TRACE":
            self._logger.debug(event, **kwargs)

    def bind(self, **kwargs: Any) -> _TraceWrapper:
        return _TraceWrapper(self._logger.bind(**kwargs))


logger = get_logger()
