# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""W3C trace context propagation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from undef.telemetry.logger.context import bind_context
from undef.telemetry.tracing.context import set_trace_context


@dataclass(frozen=True)
class PropagationContext:
    traceparent: str | None
    tracestate: str | None
    baggage: str | None
    trace_id: str | None
    span_id: str | None


def _extract_header(scope: dict[str, Any], key: bytes) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == key:
            if isinstance(value, bytes):
                return value.decode("utf-8")
            if isinstance(value, str):
                return value
            return None
    return None


def _parse_traceparent(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return (None, None)
    parts = value.split("-")
    if len(parts) != 4:
        return (None, None)
    _, trace_id, span_id, _ = parts
    if len(trace_id) != 32 or len(span_id) != 16:
        return (None, None)
    try:
        int(trace_id, 16)
        int(span_id, 16)
    except ValueError:
        return (None, None)
    return (trace_id, span_id)


def extract_w3c_context(scope: dict[str, Any]) -> PropagationContext:
    traceparent = _extract_header(scope, b"traceparent")
    tracestate = _extract_header(scope, b"tracestate")
    baggage = _extract_header(scope, b"baggage")
    trace_id, span_id = _parse_traceparent(traceparent)
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
    if context.tracestate is not None:
        bind_context(tracestate=context.tracestate)
    if context.baggage is not None:
        bind_context(baggage=context.baggage)
    if context.trace_id is not None or context.span_id is not None:
        set_trace_context(context.trace_id, context.span_id)


def clear_propagation_context() -> None:
    set_trace_context(None, None)
