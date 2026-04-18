# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""W3C trace context propagation helpers."""

from __future__ import annotations

__all__ = [
    "PropagationContext",
    "bind_propagation_context",
    "clear_propagation_context",
    "extract_w3c_context",
    "parse_baggage",
]

import contextvars
from dataclasses import dataclass
from typing import Any

from provide.telemetry._otel import attach_w3c_context, detach_w3c_context
from provide.telemetry.headers import get_header
from provide.telemetry.logger.context import bind_context, get_context, unbind_context
from provide.telemetry.tracing.context import get_trace_context, set_trace_context

_MAX_HEADER_LENGTH = 512
_MAX_TRACESTATE_PAIRS = 32
_MAX_BAGGAGE_LENGTH = 8192

_MISSING = object()
_restore_stack: contextvars.ContextVar[tuple[dict[str, object], ...]] = contextvars.ContextVar(
    "_propagation_restore_stack", default=()
)


@dataclass(frozen=True, slots=True)
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
    if raw_traceparent and len(raw_traceparent) > _MAX_HEADER_LENGTH:  # pragma: no mutate
        raw_traceparent = None  # pragma: no mutate
    if tracestate and len(tracestate) > _MAX_HEADER_LENGTH:
        tracestate = None
    if tracestate and tracestate.count(",") + 1 > _MAX_TRACESTATE_PAIRS:
        tracestate = None
    if baggage and len(baggage) > _MAX_BAGGAGE_LENGTH:
        baggage = None
    trace_id, span_id = _parse_traceparent(raw_traceparent)
    traceparent = raw_traceparent if trace_id is not None and span_id is not None else None  # pragma: no mutate
    return PropagationContext(
        traceparent=traceparent,
        tracestate=tracestate,
        baggage=baggage,
        trace_id=trace_id,
        span_id=span_id,
    )


def parse_baggage(raw: str) -> dict[str, str]:
    """Parse a W3C baggage header into key-value pairs.

    Format: ``key1=value1,key2=value2;property1=p1``
    Properties after ``;`` are stripped (metadata, not propagated values).
    Keys and values are stripped of whitespace. Empty keys are skipped.
    """
    result: dict[str, str] = {}
    for member in raw.split(","):
        kv = member.split(";", 1)[0]  # strip properties  # pragma: no mutate
        if "=" not in kv:
            continue
        key, _, value = kv.partition("=")
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


def bind_propagation_context(context: PropagationContext) -> None:
    logger_ctx = get_context()
    trace_ctx = get_trace_context()
    # Attach OTel context before snapshotting so the token is owned by this frame.
    otel_token: object | None = None
    if context.traceparent is not None:
        otel_token = attach_w3c_context(context.traceparent, context.tracestate)
    snapshot: dict[str, object] = {
        "traceparent": logger_ctx.get("traceparent", _MISSING),
        "tracestate": logger_ctx.get("tracestate", _MISSING),
        "baggage": logger_ctx.get("baggage", _MISSING),
        "trace_id": trace_ctx["trace_id"],
        "span_id": trace_ctx["span_id"],
        "otel_token": otel_token,
        "_baggage_keys": [],  # pragma: no mutate — line 145 always sets the correct key when baggage present
    }
    stack = _restore_stack.get()
    _restore_stack.set((*stack, snapshot))
    if context.traceparent is not None:
        bind_context(traceparent=context.traceparent)
    if context.tracestate is not None:
        bind_context(tracestate=context.tracestate)
    if context.baggage is not None:
        bind_context(baggage=context.baggage)
        # Auto-inject parsed baggage entries as baggage.* context fields
        parsed_keys: list[str] = []
        for key, value in parse_baggage(context.baggage).items():
            ctx_key = f"baggage.{key}"
            bind_context(**{ctx_key: value})
            parsed_keys.append(ctx_key)
        snapshot["_baggage_keys"] = parsed_keys
    if context.trace_id is not None or context.span_id is not None:
        set_trace_context(context.trace_id, context.span_id)


def clear_propagation_context() -> None:
    stack = _restore_stack.get()
    if stack:
        previous = stack[-1]
        _restore_stack.set(stack[:-1])
    else:
        previous = {
            "traceparent": _MISSING,
            "tracestate": _MISSING,
            "baggage": _MISSING,
            "trace_id": None,
            "span_id": None,
            "otel_token": None,  # pragma: no mutate
        }
    # Detach only the OTel token introduced by this specific bind frame.
    detach_w3c_context(previous.get("otel_token"))
    for key in ("traceparent", "tracestate", "baggage"):
        value = previous[key]
        if value is _MISSING:
            unbind_context(key)
        else:
            bind_context(**{key: value})
    # Unbind auto-injected baggage.* keys from the cleared frame.
    raw_keys = previous.get("_baggage_keys", [])  # pragma: no mutate
    for bkey in raw_keys if isinstance(raw_keys, list) else []:
        unbind_context(str(bkey))
    prev_trace_id = previous["trace_id"]
    prev_span_id = previous["span_id"]
    set_trace_context(
        prev_trace_id if isinstance(prev_trace_id, str) or prev_trace_id is None else None,  # pragma: no mutate
        prev_span_id if isinstance(prev_span_id, str) or prev_span_id is None else None,  # pragma: no mutate
    )
