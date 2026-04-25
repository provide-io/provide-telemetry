# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Logging setup and accessors."""

from __future__ import annotations

import logging
import sys
import threading
import warnings
from typing import Any, Protocol, cast

import structlog

from provide.telemetry import _otel
from provide.telemetry._endpoint import validate_otlp_endpoint
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler
from provide.telemetry.logger.pretty import PrettyRenderer
from provide.telemetry.logger.processors import (
    add_error_fingerprint,
    add_standard_fields,
    apply_sampling,
    enforce_event_schema,
    harden_input,
    inject_das_fields,
    inject_logger_name,
    make_level_filter,
    merge_runtime_context,
    rename_event_to_message,
    render_with_backpressure_extra,
    sanitize_sensitive_fields,
)

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

_LEVEL_NAME_TO_NUMERIC: dict[str, int] = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "TRACE": TRACE,
}


def _get_level(level: str) -> int:
    if (
        level == "TRACE"
    ):  # pragma: no mutate — TRACE is not a stdlib logging level; this branch is the only way to resolve it
        return TRACE
    mapped = logging.getLevelName(level)
    if isinstance(mapped, int):
        return mapped
    return logging.INFO


def _make_filtering_bound_logger(level: int) -> type:
    """Create a FilteringBoundLogger with zero-cost level guards and .trace().

    Extends structlog's FilteringBoundLogger with:
    - ``.trace()`` — routes through ``.debug(_trace=True)`` when TRACE is active
    - ``.is_debug_enabled()`` / ``.is_trace_enabled()`` — O(1) level checks
      for guarding expensive argument construction
    - Permissive no-op — accepts ``log.debug(key=val)`` without event string
    """
    structlog_level = max(level, logging.DEBUG)
    cls = structlog.make_filtering_bound_logger(structlog_level)

    # Permissive no-op for filtered methods (accepts any args/kwargs)
    _standard_levels = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,  # pragma: no mutate — dict literal entry; value asserted through structlog integration tests
    }

    def _permissive_nop(*_args: Any, **_kw: Any) -> None:
        return None

    for method_name, method_level in _standard_levels.items():
        if method_level < structlog_level:
            setattr(cls, method_name, _permissive_nop)

    # .trace() — forwards through debug() with _trace marker when TRACE active
    if level <= TRACE:

        def _trace(self: Any, event: str, **kw: Any) -> None:
            self.debug(event, _trace=True, **kw)
    else:
        _trace = _permissive_nop
    setattr(cls, "trace", _trace)  # noqa: B010  # pragma: no mutate — API name string is load-bearing; mutation would rename the public method

    # .is_debug_enabled() / .is_trace_enabled() — baked in at class creation
    _debug_ok = level <= logging.DEBUG
    _trace_ok = level <= TRACE
    setattr(cls, "is_debug_enabled", lambda _self: _debug_ok)  # noqa: B010  # pragma: no mutate — public attribute name; mutation would break level-check API
    setattr(cls, "is_trace_enabled", lambda _self: _trace_ok)  # noqa: B010  # pragma: no mutate — public attribute name; mutation would break level-check API

    return cls


_configured = False
_lock = threading.Lock()
_active_config: TelemetryConfig | None = None
_otel_log_provider: object | None = None
_otel_log_global_set: bool = False  # True once we called set_logger_provider()


def _has_otel_logs() -> bool:
    return _otel.has_otel()


class _InstrumentationLoggingHandlerFactory(Protocol):
    def __call__(
        self,
        level: int,
        logger_provider: object | None,
        log_code_attributes: bool,
        **kwargs: object,
    ) -> logging.Handler: ...


def _load_otel_logs_components() -> tuple[Any, Any, Any, Any, Any] | None:
    if not _has_otel_logs():
        return None
    return _otel.load_otel_logs_components()


def _load_instrumentation_logging_handler() -> _InstrumentationLoggingHandlerFactory | None:
    return _otel.load_instrumentation_logging_handler()


def _log_provider_config_key(config: TelemetryConfig) -> tuple[object, ...]:
    return (
        config.service_name,
        config.version,
        config.logging.otlp_endpoint,
        tuple(sorted(config.logging.otlp_headers.items())),
        config.exporter.logs_timeout_seconds,
    )


def _can_reuse_otel_log_provider(previous: TelemetryConfig | None, current: TelemetryConfig) -> bool:
    if previous is None or _otel_log_provider is None or not _otel_log_global_set:
        return False
    return _log_provider_config_key(previous) == _log_provider_config_key(current)


def _make_otel_logging_handler(
    sdk_logs_mod: Any, provider: object, level: int, config: TelemetryConfig
) -> logging.Handler:
    instrumentation_handler_cls = _load_instrumentation_logging_handler()
    if instrumentation_handler_cls is not None:
        return instrumentation_handler_cls(
            level=level,
            logger_provider=provider,
            log_code_attributes=config.logging.log_code_attributes,
        )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return cast(  # pragma: no mutate — cast() is a no-op at runtime; node starts here
            logging.Handler,
            sdk_logs_mod.LoggingHandler(level=level, logger_provider=provider),
        )


def _build_handlers(config: TelemetryConfig, level: int) -> list[logging.Handler]:
    global _otel_log_provider, _otel_log_global_set
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stderr)
    ]  # pragma: no mutate — stderr default is an explicit design choice; target stream asserted by integration tests

    if not config.logging.otlp_endpoint:
        return handlers

    components = _load_otel_logs_components()
    if components is None:
        return handlers

    from provide.telemetry.resilience import run_with_resilience
    from provide.telemetry.resilient_exporter import wrap_exporter

    logs_api_mod, sdk_logs_mod, sdk_logs_export_mod, resource_cls, otlp_exporter_cls = components
    if _can_reuse_otel_log_provider(_active_config, config):
        handlers.append(_make_otel_logging_handler(sdk_logs_mod, _otel_log_provider, level, config))
        return handlers

    resource = resource_cls.create({"service.name": config.service_name, "service.version": config.version})
    provider = sdk_logs_mod.LoggerProvider(resource=resource)
    raw_exporter = run_with_resilience(
        "logs",
        lambda: otlp_exporter_cls(
            endpoint=validate_otlp_endpoint(config.logging.otlp_endpoint),
            headers=config.logging.otlp_headers,
            timeout=config.exporter.logs_timeout_seconds,
        ),
    )
    if raw_exporter is None:
        return handlers
    # Wrap so every export() call applies retry/timeout/circuit-breaker policy,
    # not just the one-shot construction probe above.
    exporter = wrap_exporter("logs", raw_exporter)
    provider.add_log_record_processor(sdk_logs_export_mod.BatchLogRecordProcessor(exporter))
    logs_api_mod.set_logger_provider(provider)
    handlers.append(_make_otel_logging_handler(sdk_logs_mod, provider, level, config))
    # Set both flags together after handler construction succeeds.
    # If construction raises, _otel_log_provider stays None and shutdown_logging()
    # will correctly find no provider to flush, rather than reporting a live
    # provider that was never fully initialised.
    _otel_log_global_set = True  # pragma: no mutate — latched True after successful provider install; boolean toggle asserted by shutdown tests
    _otel_log_provider = provider
    return handlers


def _setup_emergency_fallback(exc: Exception) -> None:
    """Configure minimal stderr-only structlog pipeline when normal setup fails."""
    global _configured, _active_config
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),  # pragma: no mutate — structlog accepts "ISO" equivalently
            structlog.dev.ConsoleRenderer(colors=False),  # pragma: no mutate — None is falsy like False
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )
    _configured = True
    _active_config = None
    warnings.warn(  # pragma: no mutate — emergency-path warn() is best-effort; observed via caplog in fallback tests
        f"logging setup failed, using emergency stderr fallback: {exc}",
        RuntimeWarning,
        stacklevel=3,  # pragma: no mutate — stacklevel tuning for warnings origin; semantically equivalent at any small positive int
    )


def configure_logging(
    config: TelemetryConfig, *, force: bool = False
) -> None:  # pragma: no mutate — default force=False; all call sites pass the flag explicitly
    global _configured, _active_config
    with _lock:
        if _configured and not force and _active_config == config:
            return

        try:
            _configure_logging_inner(config)
        except Exception as exc:
            _setup_emergency_fallback(exc)


def _configure_logging_inner(config: TelemetryConfig) -> None:
    global _configured, _active_config

    level = _get_level(config.logging.level)

    # Compute effective level: min of default + every module-level override.
    # Stdlib's root logger, the handlers, AND structlog's FilteringBoundLogger
    # must all filter at effective_level, otherwise records promoted via
    # module_levels are dropped before the _LevelFilter processor can
    # evaluate them (e.g. global INFO + {"probe.child": "DEBUG"} would drop
    # the DEBUG record at the stdlib root when only `level` was used here).
    effective_level = level
    for module_level_str in config.logging.module_levels.values():
        module_numeric = _LEVEL_NAME_TO_NUMERIC.get(
            module_level_str, logging.INFO
        )  # pragma: no mutate — INFO default only reached for strings already validated upstream
        if (
            module_numeric < effective_level
        ):  # pragma: no mutate — minimum-level fold; strict-less semantics verified by module-level override tests
            effective_level = module_numeric

    handlers = [_BackpressureFanoutHandler(_build_handlers(config, effective_level))]
    logging.basicConfig(level=effective_level, handlers=handlers, format="%(message)s", force=True)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        merge_runtime_context,
        inject_logger_name,
        inject_das_fields,
        structlog.processors.add_log_level,
    ]
    if config.logging.include_timestamp:
        processors.append(structlog.processors.TimeStamper(fmt="iso"))

    processors.extend(
        [
            harden_input(
                config.security.max_attr_value_length,
                config.security.max_attr_count,
                config.security.max_nesting_depth,
            ),
            add_standard_fields(config),
            add_error_fingerprint,
            # Schema validation runs BEFORE sampling. Schema-invalid records are now
            # annotated with _schema_error and continue through the pipeline — they
            # DO contribute to emitted_logs. The ordering ensures _schema_error is
            # set before apply_sampling evaluates the record.
            enforce_event_schema(config),
        ]
    )

    # Per-module level filter — runs BEFORE apply_sampling so we don't
    # acquire backpressure tickets for records the filter is going to drop,
    # AND so the DropEvent path doesn't strand a ticket between
    # apply_sampling (acquire) and the final renderer/handler boundary.
    if config.logging.module_levels:
        processors.append(make_level_filter(config.logging.level, config.logging.module_levels))

    processors.extend(
        [
            apply_sampling,
            sanitize_sensitive_fields(config.logging.sanitize, config.pii_max_depth),
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
        # Rename structlog's internal 'event' key to canonical 'message' so that
        # all four language loggers emit the same field name in JSON output.
        processors.append(rename_event_to_message)
        renderer = structlog.processors.JSONRenderer()
    elif config.logging.fmt == "pretty":
        from provide.telemetry.logger.pretty import resolve_color

        renderer = PrettyRenderer(  # pragma: no mutate — renderer constructor; outputs verified via snapshot/console tests
            colors=sys.stderr.isatty(),
            key_color=resolve_color(
                config.logging.pretty_key_color
            ),  # pragma: no mutate — color resolution is formatting-only
            value_color=resolve_color(
                config.logging.pretty_value_color
            ),  # pragma: no mutate — color resolution is formatting-only
            fields=config.logging.pretty_fields,  # pragma: no mutate — field list plumbing; exact sequence asserted by pretty render tests
        )
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    processors.append(render_with_backpressure_extra(renderer))

    structlog.configure(
        processors=processors,
        wrapper_class=_make_filtering_bound_logger(effective_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    _active_config = config
    _configured = True


def shutdown_logging() -> None:
    global _configured, _active_config, _otel_log_provider
    with _lock:
        provider = _otel_log_provider
        if provider is None:
            _configured = False
            _active_config = None
            return
        try:
            flush = getattr(provider, "force_flush", None)
            if callable(flush):
                flush()
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
        finally:
            _otel_log_provider = None
            _active_config = None
            _configured = False


def _reset_logging_for_tests() -> None:
    global _configured, _active_config, _otel_log_provider, _otel_log_global_set
    with _lock:
        _configured = False
        _active_config = None
        _otel_log_provider = None
        _otel_log_global_set = False


def _has_otel_log_provider() -> bool:
    """Return True if an OTel log provider is installed or was ever installed (thread-safe)."""
    with _lock:
        return _otel_log_provider is not None or _otel_log_global_set


def _has_real_otel_log_provider() -> bool:
    """Return True if a live OTel log provider is currently installed."""
    with _lock:
        return _otel_log_provider is not None


def get_logger(name: str | None = None) -> _TraceWrapper:
    if not _configured:
        from provide.telemetry.config import TelemetryConfig
        from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy

        cfg = TelemetryConfig.from_env()
        # Install the logs sampling policy so PROVIDE_SAMPLING_LOGS_RATE takes
        # effect for lazy-init emission.  Narrow on purpose: leave exporter and
        # backpressure policies alone — those belong to setup_telemetry()'s
        # orchestration, and overwriting them here would clobber values set
        # directly by callers that only want logging without full setup.
        set_sampling_policy("logs", SamplingPolicy(default_rate=cfg.sampling.logs_rate))
        configure_logging(cfg)
    return _TraceWrapper(structlog.get_logger(name or "provide"))


def is_debug_enabled() -> bool:
    """Standalone check if debug-level logging is enabled.

    Use to guard expensive argument construction::

        from provide.telemetry.logger import is_debug_enabled
        if is_debug_enabled():
            logger.debug("result", payload=model.model_dump_json())
    """
    with _lock:
        active = _active_config
    if active is None:
        return True  # unconfigured — let everything through
    return _get_level(active.logging.level) <= logging.DEBUG


def is_trace_enabled() -> bool:
    """Standalone check if trace-level logging is enabled."""
    with _lock:
        active = _active_config
    if active is None:
        return True
    return _get_level(active.logging.level) <= TRACE


class _TraceWrapper:
    """Thin wrapper that forwards to the structlog bound logger.

    The custom FilteringBoundLogger (from ``_make_filtering_bound_logger``)
    already provides ``.trace()``, ``.is_debug_enabled()``, and
    ``.is_trace_enabled()`` — this wrapper just preserves the return type
    on ``.bind()``.
    """

    __slots__ = ("_logger",)

    def __init__(self, logger: Any) -> None:
        self._logger = logger

    def __getattr__(self, item: str) -> Any:
        return getattr(self._logger, item)

    def trace(self, event: str, **kwargs: Any) -> None:
        self._logger.trace(event, **kwargs)

    def is_debug_enabled(self) -> bool:
        return bool(self._logger.is_debug_enabled())

    def is_trace_enabled(self) -> bool:
        return bool(self._logger.is_trace_enabled())

    def bind(self, **kwargs: Any) -> _TraceWrapper:
        return _TraceWrapper(self._logger.bind(**kwargs))


class _LazyLogger:
    def _resolve(self) -> _TraceWrapper:
        return get_logger()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._resolve(), item)

    def trace(self, event: str, **kwargs: Any) -> None:
        self._resolve().trace(event, **kwargs)

    def is_debug_enabled(self) -> bool:
        return self._resolve().is_debug_enabled()

    def is_trace_enabled(self) -> bool:
        return self._resolve().is_trace_enabled()

    def bind(self, **kwargs: Any) -> _TraceWrapper:
        return self._resolve().bind(**kwargs)


logger = _LazyLogger()
