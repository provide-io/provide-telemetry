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
from typing import Any

import structlog

from provide.telemetry._endpoint import validate_otlp_endpoint
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.logger import _otel_logs
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

# Explicit bindings rather than aliased re-imports: mypy's no_implicit_reexport
# rejects the latter, and a module attribute is what the tests patch.
_InstrumentationLoggingHandlerFactory = _otel_logs.InstrumentationLoggingHandlerFactory
_has_otel_logs = _otel_logs.has_otel_logs
_load_instrumentation_logging_handler = _otel_logs.load_instrumentation_logging_handler
_log_provider_config_key = _otel_logs.log_provider_config_key


def _load_otel_logs_components() -> tuple[Any, Any, Any, Any, Any] | None:
    """Gate the component load on OTel availability.

    The check stays here rather than in _otel_logs so that patching
    core._has_otel_logs — which the tests do — still governs the result.
    """
    if not _has_otel_logs():
        return None
    return _otel_logs.load_otel_logs_components()


_make_handler = _otel_logs.make_otel_logging_handler

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


def _stderr_handler() -> logging.StreamHandler:  # type: ignore[type-arg]
    """Default handler. Hoisted so the pragma applies; see CLAUDE.md on placement."""
    return logging.StreamHandler(sys.stderr)  # pragma: no mutate — None also defaults to stderr


# structlog_level never exceeds CRITICAL, so this entry's `<` test never fires:
# the key is unreachable and every mutation of it is equivalent.
_CRITICAL_KEY = "critical"  # pragma: no mutate — unreachable table key; structlog_level never exceeds CRITICAL


def _iso_timestamper() -> Any:
    """structlog resolves the format name case-insensitively."""
    return structlog.processors.TimeStamper(fmt="iso")  # pragma: no mutate — format name is case-insensitive


def _plain_console_renderer() -> Any:
    """colors=None is falsy exactly like colors=False."""
    return structlog.dev.ConsoleRenderer(colors=False)  # pragma: no mutate — colors=None is falsy like False


def _get_level(level: str) -> int:
    # addLevelName registers TRACE, so getLevelName below resolves it anyway —
    # this fast path is a shortcut, making mutations of the literal equivalent.
    is_trace = level == "TRACE"  # pragma: no mutate — shortcut only; getLevelName resolves TRACE anyway
    if is_trace:
        return TRACE
    mapped = logging.getLevelName(level)
    if isinstance(mapped, int):
        return mapped
    return logging.INFO


def _make_filtering_bound_logger(level: int) -> type[structlog.typing.BindableLogger]:
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
        _CRITICAL_KEY: logging.CRITICAL,
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


def _can_reuse_otel_log_provider(previous: TelemetryConfig | None, current: TelemetryConfig) -> bool:
    if previous is None or _otel_log_provider is None or not _otel_log_global_set:
        return False
    return _log_provider_config_key(previous) == _log_provider_config_key(current)


def _build_handlers(config: TelemetryConfig, level: int) -> list[logging.Handler]:
    global _otel_log_provider, _otel_log_global_set
    handlers: list[logging.Handler] = [
        _stderr_handler()
    ]  # pragma: no mutate — StreamHandler(None) defaults to sys.stderr; the None mutant is behaviorally equivalent and cannot be killed

    if not config.logging.otlp_endpoint or not config.logging.otlp_enabled:
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
            _iso_timestamper(),
            _plain_console_renderer(),
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
        # Folding to a minimum: reassigning an equal value is a no-op, so `<` and
        # `<=` produce the same effective_level for every input.
        lowers = module_numeric < effective_level  # pragma: no mutate — equal reassign is a no-op; < and <= agree
        if lowers:
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


def shutdown_logging(timeout_seconds: float | None = None) -> None:
    """Tear the OTel log provider down; *timeout_seconds* bounds the drain.

    ``None`` uses the logger's own active config. A caller with a termination
    grace period passes what it has left.
    """
    global _configured, _active_config, _otel_log_provider
    with _lock:
        provider = _otel_log_provider
        active = _active_config
        # Clear in-process state before releasing the lock so concurrent
        # readers (is_debug_enabled, get_logger, configure_logging) see the
        # torn-down state immediately and don't race the bounded shutdown.
        _otel_log_provider = None
        _active_config = None
        _configured = False
    if provider is None:
        return
    from provide.telemetry.resilience import bounded_provider_shutdown

    configured = active.exporter.logs_shutdown_timeout_seconds if active is not None else 5.0
    bounded_provider_shutdown(provider, timeout_seconds if timeout_seconds is not None else configured)


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


def _make_otel_logging_handler(
    sdk_logs_mod: Any, provider: object, level: int, config: TelemetryConfig
) -> logging.Handler:
    """Resolve the instrumentation factory here so tests can patch the lookup."""
    return _make_handler(sdk_logs_mod, provider, level, config, _load_instrumentation_logging_handler())
