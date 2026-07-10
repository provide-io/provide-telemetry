# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tracing decorators and the shared span lifecycle.

``_open_span`` is the single implementation of the span lifecycle —
consent → sampling → backpressure → health → start span → mirror the OTel
trace/span IDs into our contextvars (for log correlation) → restore context
and release the backpressure ticket on exit. Both the ``@trace`` decorator
(here) and the block-level ``span()`` context manager (in
:mod:`provide.telemetry.tracing.span`) are thin wrappers over it, so the
governance and correlation behaviour is written, tested, and mutated once.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, ParamSpec, TypeVar, cast

from provide.telemetry.tracing.context import get_span_id, get_trace_id, set_trace_context
from provide.telemetry.tracing.provider import _NoopSpan, _sync_otel_trace_context, get_tracer

P = ParamSpec("P")
R = TypeVar("R")


@contextmanager
def _open_span(name: str, scope: str | None = None) -> Iterator[Any]:
    """Run the shared span lifecycle, yielding the active span.

    When consent, sampling, or backpressure denies the span, yields a
    :class:`_NoopSpan` and runs the caller's body untraced (no health count, no
    ticket, no context change) — mirroring the decorator's pre-existing bypass
    behaviour. Otherwise starts the span under ``scope`` (instrumentation name),
    syncs its IDs into our contextvars, and on exit restores the prior context
    and releases the ticket.
    """
    from provide.telemetry.backpressure import release, try_acquire
    from provide.telemetry.health import increment_emitted
    from provide.telemetry.sampling import should_sample

    try:
        from provide.telemetry.consent import should_allow
    except ImportError:  # pragma: no cover — governance module stripped

        def should_allow(signal: str, log_level: str | None = None) -> bool:  # noqa: ARG001
            return True

    if not should_allow("traces"):
        yield _NoopSpan(name)
        return
    # When a live OTel tracer provider is installed the SDK ParentBased
    # TraceIdRatioBased sampler is authoritative — skip facade should_sample
    # so we do not double-sample. Without a live provider, should_sample remains
    # the only probabilistic gate (noop path).
    from provide.telemetry.tracing.provider import _has_live_tracing_provider

    if not _has_live_tracing_provider() and not should_sample("traces", name):
        yield _NoopSpan(name)
        return
    ticket = try_acquire("traces")
    if ticket is None:
        yield _NoopSpan(name)
        return
    increment_emitted("traces")
    prev_trace = get_trace_id()
    prev_span = get_span_id()
    try:
        with get_tracer(scope).start_as_current_span(name) as sp:
            _sync_otel_trace_context()
            yield sp
    finally:
        set_trace_context(prev_trace, prev_span)
        release(ticket)


def trace(name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = str(name or getattr(fn, "__name__", fn.__class__.__name__))

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                with _open_span(span_name, fn.__module__):
                    return await fn(*args, **kwargs)

            return cast(
                Callable[P, R], async_wrapper
            )  # pragma: no mutate — typing-only cast; runtime value is the wrapper itself

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with _open_span(span_name, fn.__module__):
                return fn(*args, **kwargs)

        return cast(
            Callable[P, R], sync_wrapper
        )  # pragma: no mutate — typing-only cast; runtime value is the wrapper itself

    return decorator
