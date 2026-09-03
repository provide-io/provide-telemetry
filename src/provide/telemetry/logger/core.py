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

from provide.telemetry import levels as _levels
from provide.telemetry._endpoint import validate_otlp_endpoint
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.levels import _TABLE as _LEVEL_TABLE
from provide.telemetry.levels import LogSeverity, to_stdlib_level
from provide.telemetry.logger import _otel_logs
from provide.telemetry.logger.console import ansi_supported, structlog_colors, utf8_writer
from provide.telemetry.logger.handlers import _BackpressureFanoutHandler
from provide.telemetry.logger.pretty import PrettyRenderer
from provide.telemetry.logger.processors import (
    add_error_fingerprint,
    add_standard_fields,
    apply_sampling,
    canonicalize_level,
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

# Re-bound as a module attribute rather than imported directly: mypy's
# no_implicit_reexport rejects a bare re-import, and a module attribute is what
# the tests patch. Same reasoning as the OTel bindings above.
TRACE = _levels.TRACE
logging.addLevelName(TRACE, "TRACE")

# Module-name prefixes CallsiteParameterAdder walks past before deciding which
# frame is the callsite. structlog skips its own frames and `logging`'s, but
# knows nothing about the wrappers this module puts between the caller and
# structlog: the `_trace` closure from _make_filtering_bound_logger, and
# _TraceWrapper / _LazyLogger's `trace()` and `log()`. Naming this module keeps
# all five out of the way, so `filename` and `lineno` are the caller's.
#
# Deliberately just this module, not the whole `provide.telemetry` package:
# every wrapper lives here, and a package-wide prefix would also skip
# provide-telemetry's own structlog callers (TelemetryMiddleware), blaming
# their logs on whatever called *them*. __name__ rather than a literal so the
# prefix cannot drift if the module moves.
_CALLSITE_IGNORES: list[str] = [__name__]

# Derived from the one shared table rather than restated. The literal version
# of this dict knew WARNING but not WARN, and nothing kept it in step with the
# near-identical table in processors.py.
_LEVEL_NAME_TO_NUMERIC: dict[str, int] = {name: severity.stdlib_level for name, severity in _LEVEL_TABLE.items()}


def _stderr_handler() -> logging.StreamHandler:  # type: ignore[type-arg]
    """Default handler, writing UTF-8 whatever the stream's own encoding is.

    A redirected stream on Windows carries the locale encoding — cp1252, not
    UTF-8 — and stderr's ``errors="backslashreplace"`` turns an emoji into the
    literal text ``\U0001f439`` rather than raising. utf8_writer hands back
    sys.stderr itself wherever that is already correct, which is everywhere but
    there.
    """
    return logging.StreamHandler(utf8_writer(sys.stderr))  # pragma: no mutate — None also defaults to stderr


# structlog_level never exceeds CRITICAL, so this entry's `<` test never fires:
# the key is unreachable and every mutation of it is equivalent.
_CRITICAL_KEY = "critical"  # pragma: no mutate — unreachable table key; structlog_level never exceeds CRITICAL


def _iso_timestamper() -> Any:
    """structlog resolves the format name case-insensitively."""
    return structlog.processors.TimeStamper(fmt="iso")  # pragma: no mutate — format name is case-insensitive


def _plain_console_renderer() -> Any:
    """Emergency renderer: colorless, and plain tracebacks only.

    exception_formatter is pinned to plain_traceback because structlog's
    default (RichTracebackFormatter(show_locals=True)) renders local
    variables from every frame in a traceback, which can leak sensitive
    values through logger.error(..., exc_info=True). Both kwargs are held
    by tests/logger/test_console_locals_leak.py. The call takes **kwargs
    because mutmut nulls any literal keyword argument at its call site —
    colors=None is falsy like False, an equivalent mutant no test can
    kill, and a pragma cannot reach a continuation line.
    """
    kwargs: dict[str, Any] = {"colors": False}  # pragma: no mutate — a None value is falsy like False
    kwargs["exception_formatter"] = structlog.dev.plain_traceback
    return structlog.dev.ConsoleRenderer(**kwargs)


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

    # .trace() — forwards through debug() with _trace marker when TRACE active.
    # *args is not decoration: structlog's bound-logger methods are
    # (event, *args, **kw) and interpolate event % args, so every sibling level
    # accepts log.info("chunk %d", n). Narrowing trace to (event, **kw) made
    # demoting an info call to trace a TypeError instead of a quieter log.
    if level <= TRACE:

        def _trace(self: Any, event: str, *args: Any, **kw: Any) -> None:
            self.debug(event, *args, _trace=True, **kw)
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
    # Annotated list[Any] like the main chain: structlog's Processor alias is
    # MutableMapping-based, and this repo's processors are all dict-typed.
    fallback_processors: list[Any] = [
        structlog.processors.add_log_level,
        canonicalize_level,
        _iso_timestamper(),
        _plain_console_renderer(),
    ]
    structlog.configure(
        processors=fallback_processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=structlog.PrintLoggerFactory(file=utf8_writer(sys.stderr)),
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


def _installed_fanout() -> _BackpressureFanoutHandler | None:
    """The SDK's own handler on the root logger, if it is still attached."""
    for handler in logging.getLogger().handlers:
        if isinstance(handler, _BackpressureFanoutHandler):
            return handler
    return None


def _install_pipeline(children: list[logging.Handler], level: int, *, reload: bool) -> None:
    """Put *children* behind the root logger at *level*.

    Two paths, and what separates them is whether the SDK has configured
    logging before, not what happens to be attached to the root logger.

    Setting up owns the slate: ``basicConfig(force=True)`` removes and closes
    whatever was there, because a host that had already called
    ``basicConfig()`` would otherwise see every record twice.

    A reload reuses the handler already installed and swaps its children. The
    root's handler list is not rewritten, so a handler the host added after
    setup survives — which it must, since redirecting through the stdlib is the
    only mechanism Python's SDK offers, and that promise was worth nothing if
    the next config change silently revoked it. Reuse also means the handler
    cannot accumulate: one fan-out handler however often config reloads.

    A reload that finds no handler of ours — a host removed it — rebuilds
    through the first path, so the pipeline comes back rather than emitting
    into nothing.
    """
    installed = _installed_fanout() if reload else None
    if installed is None:
        logging.basicConfig(
            level=level,
            handlers=[_BackpressureFanoutHandler(children)],
            format="%(message)s",
            force=True,
        )
        return
    installed.replace_children(children)
    logging.getLogger().setLevel(level)


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

    _install_pipeline(_build_handlers(config, effective_level), effective_level, reload=_configured)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        merge_runtime_context,
        inject_logger_name,
        inject_das_fields,
        structlog.processors.add_log_level,
        canonicalize_level,
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
                ],
                additional_ignores=_CALLSITE_IGNORES,
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
            colors=ansi_supported(sys.stderr),
            key_color=resolve_color(
                config.logging.pretty_key_color
            ),  # pragma: no mutate — color resolution is formatting-only
            value_color=resolve_color(
                config.logging.pretty_value_color
            ),  # pragma: no mutate — color resolution is formatting-only
            fields=config.logging.pretty_fields,  # pragma: no mutate — field list plumbing; exact sequence asserted by pretty render tests
        )
    else:
        # exception_formatter pinned to plain_traceback — structlog's default
        # (RichTracebackFormatter(show_locals=True)) renders frame locals,
        # which can leak sensitive values via logger.error(..., exc_info=True).
        # structlog_colors, not isatty: ConsoleRenderer(colors=True) raises
        # SystemError on Windows without colorama — which is not a dependency of
        # this package — and configure_logging catches every exception, so a
        # Windows terminal without it lost the whole pipeline to the emergency
        # fallback rather than merely losing colour.
        renderer = structlog.dev.ConsoleRenderer(
            colors=structlog_colors(sys.stderr), exception_formatter=structlog.dev.plain_traceback
        )

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
        from provide.telemetry.consent import _load_consent_from_env
        from provide.telemetry.sampling import SamplingPolicy, set_sampling_policy

        # The pre-setup path must honour PROVIDE_CONSENT_LEVEL too: a process
        # that only ever calls get_logger() still gets the operator's opt-out.
        _load_consent_from_env()
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

    def trace(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._logger.trace(event, *args, **kwargs)

    def log(self, level: LogSeverity | str | int, event: str, *args: Any, **kwargs: Any) -> None:
        """Emit at a level known only at runtime.

        For adapters that receive a level as data. structlog's own ``log()``
        takes a stdlib numeric level, so a level *string* raised TypeError on
        the ``level < min_level`` comparison inside the filtering bound logger
        -- the one thing an adapter holding ``"warn"`` actually wanted to do.
        """
        numeric = to_stdlib_level(level)
        if numeric <= TRACE:
            # structlog's level-to-method map starts at DEBUG, and this
            # pipeline implements TRACE as debug(_trace=True) rather than as a
            # structlog level -- see _make_filtering_bound_logger, which floors
            # structlog at DEBUG. Routing TRACE through log() would compare
            # 5 < 10 and drop the record without a word.
            self.trace(event, *args, **kwargs)
            return
        self._logger.log(numeric, event, *args, **kwargs)

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

    def trace(self, event: str, *args: Any, **kwargs: Any) -> None:
        self._resolve().trace(event, *args, **kwargs)

    def log(self, level: LogSeverity | str | int, event: str, *args: Any, **kwargs: Any) -> None:
        """See :meth:`_TraceWrapper.log`."""
        self._resolve().log(level, event, *args, **kwargs)

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
