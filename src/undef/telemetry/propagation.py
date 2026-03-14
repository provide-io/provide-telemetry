# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""W3C trace context propagation helpers."""

from __future__ import annotations

__all__ = [
    "PropagationContext",
    "bind_propagation_context",
    "clear_propagation_context",
    "extract_w3c_context",
]

import contextvars
from dataclasses import dataclass
from typing import Any

from undef.telemetry._otel import attach_w3c_context, detach_w3c_context
from undef.telemetry.headers import get_header
from undef.telemetry.logger.context import bind_context
from undef.telemetry.tracing.context import set_trace_context

_otel_context_token: contextvars.ContextVar[object | None] = contextvars.ContextVar("_otel_context_token", default=None)
_otel_reset_token: contextvars.ContextVar[contextvars.Token[object | None] | None] = contextvars.ContextVar(
    "_otel_reset_token", default=None
)


@dataclass(frozen=True)
class PropagationContext:
    traceparent: str | None
    tracestate: str | None
    baggage: str | None
    trace_id: str | None
    span_id: str | None


def _extract_header(scope: dict[str, Any], key: bytes) -> str | None:
    return get_header(scope, key)


def _parse_traceparent(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return (None, None)
    parts = value.split("-")
    if len(parts) != 4:
        return (None, None)
    version, trace_id, span_id, trace_flags = parts
    if len(version) != 2 or len(trace_id) != 32 or len(span_id) != 16 or len(trace_flags) != 2:
        return (None, None)
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return (None, None)
    if version.lower() == "ff":
        return (None, None)
    try:
        int(version, 16)  # pragma: no mutate
        int(trace_id, 16)  # pragma: no mutate
        int(span_id, 16)  # pragma: no mutate
        int(trace_flags, 16)  # pragma: no mutate
    except ValueError:
        return (None, None)
    return (trace_id.lower(), span_id.lower())


def extract_w3c_context(scope: dict[str, Any]) -> PropagationContext:
    raw_traceparent = _extract_header(scope, b"traceparent")
    tracestate = _extract_header(scope, b"tracestate")
    baggage = _extract_header(scope, b"baggage")
    trace_id, span_id = _parse_traceparent(raw_traceparent)
    traceparent = raw_traceparent if trace_id is not None and span_id is not None else None  # pragma: no mutate
    return PropagationContext(
        traceparent=traceparent,
        tracestate=tracestate,
        baggage=baggage,
        trace_id=trace_id,
        span_id=span_id,
    )


def bind_propagation_context(context: PropagationContext) -> None:
    if context.traceparent is not None:
        bind_context(traceparent=context.traceparent)
        token = attach_w3c_context(context.traceparent, context.tracestate)
        reset_tok = _otel_context_token.set(token)
        _otel_reset_token.set(reset_tok)
    if context.tracestate is not None:
        bind_context(tracestate=context.tracestate)
    if context.baggage is not None:
        bind_context(baggage=context.baggage)
    if context.trace_id is not None or context.span_id is not None:
        set_trace_context(context.trace_id, context.span_id)


def clear_propagation_context() -> None:
    token = _otel_context_token.get()
    detach_w3c_context(token)
    reset_tok = _otel_reset_token.get()
    if reset_tok is not None:
        try:
            _otel_context_token.reset(reset_tok)
        except ValueError:  # pragma: no cover
            _otel_context_token.set(None)
        _otel_reset_token.set(None)
    else:
        _otel_context_token.set(None)
    set_trace_context(None, None)
