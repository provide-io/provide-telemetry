# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tracer setup and acquisition."""

from __future__ import annotations

import threading
import warnings
from contextlib import AbstractContextManager
from typing import Any, Protocol, cast

from provide.telemetry import _otel
from provide.telemetry._endpoint import validate_otlp_endpoint
from provide.telemetry._resource import build_resource
from provide.telemetry.config import TelemetryConfig
from provide.telemetry.tracing.context import get_trace_context, set_trace_context


def _has_otel() -> bool:
    return _otel.has_otel()


_HAS_OTEL = _has_otel()
_provider_configured: bool = False
_provider_lock = threading.Lock()
_provider_ref: Any | None = None
_otel_global_set: bool = False  # True once we called set_tracer_provider()
_setup_generation: int = 0
_tracing_explicitly_disabled: bool = False


class _NoopSpan(AbstractContextManager["_NoopSpan"]):
    NOOP_TRACE_ID = "0" * 32
    NOOP_SPAN_ID = "0" * 16

    def __init__(self, name: str) -> None:
        self.name = name
        self.trace_id = self.NOOP_TRACE_ID
        self.span_id = self.NOOP_SPAN_ID
        self._prev_trace_id: str | None = None
        self._prev_span_id: str | None = None

    def __enter__(self) -> _NoopSpan:
        prev = get_trace_context()
        self._prev_trace_id = prev["trace_id"]
        self._prev_span_id = prev["span_id"]
        set_trace_context(self.trace_id, self.span_id)
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        set_trace_context(self._prev_trace_id, self._prev_span_id)


class _NoopTracer:
    def start_as_current_span(self, name: str, **_: object) -> _NoopSpan:
        return _NoopSpan(name)


def _refresh_otel_tracing() -> None:
    global _HAS_OTEL
    _HAS_OTEL = _has_otel()


def _load_otel_trace_api() -> Any | None:
    if not _HAS_OTEL:
        return None
    return _otel.load_otel_trace_api()


def _load_otel_tracing_components() -> tuple[Any, Any, Any, Any] | None:
    if not _HAS_OTEL:
        return None
    return _otel.load_otel_tracing_components()


def _has_tracing_provider() -> bool:
    """Return True if a tracing provider is installed or was ever installed (thread-safe)."""
    with _provider_lock:
        return _provider_ref is not None or _otel_global_set


def _has_live_tracing_provider() -> bool:
    """Return True if a live tracing provider is currently installed."""
    with _provider_lock:
        return _provider_ref is not None


def _has_effective_tracing_provider() -> bool:
    """Return True if a span started now would reach a real tracer provider.

    Distinct from :func:`_has_live_tracing_provider`, which answers "did *we*
    install one" — the question reconfiguration safety turns on. This answers
    "is one in play", which includes a provider a host application installed
    itself: such a provider owns the OTel global, so ``get_tracer()`` resolves
    it and spans export, and the facade must not apply its own probabilistic
    sampling on top of the SDK's sampler.

    Gates on ``_tracing_explicitly_disabled`` first and then delegates to the
    same predicate ``get_tracer()`` gates on — in that order, because that is
    the order ``get_tracer()`` uses. Skipping the disablement check would let
    the sampling bypass fire for spans that ``get_tracer()`` then serves from a
    ``_NoopTracer``: no export, but counted as emitted and holding a queue slot.
    """
    if _tracing_explicitly_disabled:
        return False
    if _has_live_tracing_provider():
        return True
    otel_trace = _load_otel_trace_api()
    if otel_trace is None:
        return False
    with _provider_lock:
        return _has_real_tracer_provider(otel_trace)


def setup_tracing(config: TelemetryConfig) -> None:
    global _provider_configured, _provider_ref, _otel_global_set
    global _tracing_explicitly_disabled
    if not config.tracing.enabled:
        _tracing_explicitly_disabled = True
        return
    _tracing_explicitly_disabled = False
    from provide.telemetry.resilience import _is_running_in_event_loop

    if (
        _is_running_in_event_loop()
    ):  # pragma: no mutate — event-loop guard; both branches exercised by asyncio-specific tests
        warnings.warn(  # pragma: no mutate — best-effort warning emission; exact wording is non-semantic
            "setup_tracing() called from an active event loop; "  # pragma: no mutate — warning message string is non-semantic
            "provider initialization may stall the event loop. "  # pragma: no mutate — warning message string is non-semantic
            "Call setup_telemetry() before starting the event loop.",  # pragma: no mutate — warning message string is non-semantic
            RuntimeWarning,  # pragma: no mutate — warning category; any subclass of Warning is equivalent for the catch-all tests
            stacklevel=2,  # pragma: no mutate — stacklevel tuning; any small positive int surfaces the caller frame
        )  # pragma: no mutate — closing paren line for multi-line call; trivial
    if not _HAS_OTEL:
        return

    # Make OTel's current-span contextvar tolerant of cross-context teardown
    # (async-gen aclose() from another task, cancelled/GC'd coroutines) so spans
    # in async services don't flood logs with "Failed to detach context".
    # OTel-only (context_runtime subclasses a real OTel class) and guarded: a
    # partial/absent SDK must never raise out of setup. Exercised by the
    # otel-marked test_context_runtime suite.
    try:  # pragma: no cover - requires the optional OTel SDK at runtime
        from provide.telemetry.tracing.context_runtime import install_safe_runtime_context

        install_safe_runtime_context()
    except ImportError:  # pragma: no cover - OTel SDK unavailable
        pass

    with _provider_lock:
        if _provider_configured:
            return
        gen = _setup_generation  # snapshot before releasing the lock

    # Build provider/exporter outside the lock to avoid blocking
    # concurrent get_tracer()/shutdown_tracing() during slow network I/O.
    components = _load_otel_tracing_components()
    otel_trace = _load_otel_trace_api()
    if components is None or otel_trace is None:
        return

    resource_cls, provider_cls, processor_cls, exporter_cls = components
    resource = build_resource(config, resource_cls)
    # SDK sampler is the single sampling authority for live OTel spans (global
    # tracer, instrumentations, facade). Facade should_sample is skipped when a
    # live provider is installed to avoid double-sampling.
    effective_rate = min(config.sampling.traces_rate, config.tracing.sample_rate)
    sampler = _otel.build_otel_trace_sampler(effective_rate)
    provider = (
        provider_cls(resource=resource, sampler=sampler) if sampler is not None else provider_cls(resource=resource)
    )
    if config.tracing.otlp_endpoint:
        from provide.telemetry.resilience import run_with_resilience
        from provide.telemetry.resilient_exporter import wrap_exporter

        raw_exporter = run_with_resilience(
            "traces",
            lambda: exporter_cls(
                endpoint=validate_otlp_endpoint(config.tracing.otlp_endpoint),
                headers=config.tracing.otlp_headers,
                timeout=config.exporter.traces_timeout_seconds,
            ),
        )
        if raw_exporter is None:
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
            return
        # Wrap so every export() call applies retry/timeout/circuit-breaker policy.
        provider.add_span_processor(processor_cls(wrap_exporter("traces", raw_exporter)))

    with _provider_lock:
        if _provider_configured or _setup_generation != gen:
            # Another thread won the race OR shutdown happened mid-build — discard ours.
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
            return
        otel_trace.set_tracer_provider(provider)
        _provider_ref = provider
        _provider_configured = True
        _otel_global_set = True


def shutdown_tracing() -> None:
    global _provider_ref, _provider_configured, _setup_generation
    with _provider_lock:
        _setup_generation += 1
        provider = _provider_ref
        if provider is None:
            _provider_configured = False
            return
        try:
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
        finally:
            _provider_ref = None
            _provider_configured = False


def _reset_tracing_for_tests() -> None:
    global _provider_configured, _provider_ref, _otel_global_set, _setup_generation
    global _tracing_explicitly_disabled
    _provider_configured = False
    _provider_ref = None
    _otel_global_set = False
    _setup_generation = 0
    _tracing_explicitly_disabled = False


class _TracerLike(Protocol):
    def start_as_current_span(self, name: str, **kwargs: object) -> AbstractContextManager[object]: ...


def _has_real_tracer_provider(otel_trace: Any) -> bool:
    """Return True if a usable (non-placeholder) OTel tracer provider is globally available."""
    if _provider_configured:
        return True
    if _otel_global_set:
        # We installed a provider but it was shut down; don't use the stale global.
        return False
    # Whatever owns the global now — ours is gone, so a live provider here is a
    # host application's, whether it was installed before or after our setup.
    return _otel.is_live_provider(otel_trace.get_tracer_provider())


def get_tracer(name: str | None = None) -> _TracerLike:
    if _tracing_explicitly_disabled:
        return _NoopTracer()
    otel_trace = _load_otel_trace_api()
    if otel_trace is None:
        return _NoopTracer()
    if not _has_real_tracer_provider(otel_trace):
        return _NoopTracer()
    tracer_name = "provide.telemetry" if name is None else name
    return cast(
        _TracerLike, otel_trace.get_tracer(tracer_name)
    )  # pragma: no mutate — typing-only cast; runtime value is a protocol-compatible tracer


def _sync_otel_trace_context() -> None:
    """Sync the active OTel span's trace/span IDs into our contextvars."""
    otel_trace = _load_otel_trace_api()
    if otel_trace is None:
        return
    if not _has_real_tracer_provider(otel_trace):
        return
    span = otel_trace.get_current_span()
    ctx = span.get_span_context()
    if ctx is not None and ctx.trace_id != 0 and ctx.span_id != 0:
        set_trace_context(format(ctx.trace_id, "032x"), format(ctx.span_id, "016x"))


class _LazyTracer:
    """Defers tracer resolution to call time so setup() takes effect."""

    def start_as_current_span(self, name: str, **kwargs: object) -> AbstractContextManager[object]:
        return get_tracer().start_as_current_span(name, **kwargs)


tracer: _TracerLike = _LazyTracer()
