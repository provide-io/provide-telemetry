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
    "inject_traceparent",
    "parse_baggage",
]

import contextvars
import re as _re
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from provide.telemetry._otel import attach_w3c_context, detach_w3c_context, inject_w3c_context
from provide.telemetry.headers import get_header
from provide.telemetry.logger.context import bind_context, get_context, unbind_context
from provide.telemetry.tracing.context import (
    get_span_id,
    get_trace_context,
    get_trace_id,
    set_trace_context,
)

# Snapshot field names. Defined as module constants so the pragma applies to a
# whole statement: mutmut ignores a trailing pragma on an element inside a
# multi-line dict literal. Every use is symmetric (written then read through the
# same constant), so the literal text itself is unobservable.
_OTEL_TOKEN_FIELD = "otel_token"  # noqa: S105 - a snapshot dict key, not a credential  # pragma: no mutate
_BAGGAGE_KEYS_FIELD = "_baggage_keys"  # pragma: no mutate
_BAGGAGE_PRIOR_FIELD = "_baggage_prior"  # pragma: no mutate

# RFC 7230 token, which the W3C Baggage spec requires of keys. Excludes control
# characters, whitespace and separators — see parse_baggage for why that matters.
_BAGGAGE_TOKEN_RE = _re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
# C0/C1 controls except TAB, stripped from baggage values.
_CONTROL_CHARS_RE = _re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

_MAX_HEADER_LENGTH = 512
_MAX_TRACESTATE_PAIRS = 32
_MAX_BAGGAGE_LENGTH = 8192
_TRACE_ID_LENGTH = 32
_SPAN_ID_LENGTH = 16
_HEX_DIGITS = frozenset("0123456789abcdef")

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
        int(version, 16)  # pragma: no mutate — hex-format validation; ValueError captured below covers invalid-hex path
        int(
            trace_id, 16
        )  # pragma: no mutate — hex-format validation; ValueError captured below covers invalid-hex path
        int(span_id, 16)  # pragma: no mutate — hex-format validation; ValueError captured below covers invalid-hex path
        int(
            trace_flags, 16
        )  # pragma: no mutate — hex-format validation; ValueError captured below covers invalid-hex path
    except ValueError:
        return (None, None)
    return (trace_id.lower(), span_id.lower())


def extract_w3c_context(scope: dict[str, Any]) -> PropagationContext:
    raw_traceparent = _extract_header(scope, b"traceparent")
    tracestate = _extract_header(scope, b"tracestate")
    baggage = _extract_header(scope, b"baggage")
    # A traceparent is a fixed 55 characters, so nothing at or beyond this bound
    # can ever parse: the boundary (> vs >=) and the replacement value (None vs
    # any other falsy) both fold to the same (None, None) parse result.
    oversized = bool(raw_traceparent) and len(raw_traceparent or "") > _MAX_HEADER_LENGTH  # pragma: no mutate
    if oversized:
        raw_traceparent = None  # pragma: no mutate
    if tracestate and len(tracestate) > _MAX_HEADER_LENGTH:
        tracestate = None
    if tracestate and tracestate.count(",") + 1 > _MAX_TRACESTATE_PAIRS:
        tracestate = None
    if baggage and len(baggage) > _MAX_BAGGAGE_LENGTH:
        baggage = None
    trace_id, span_id = _parse_traceparent(raw_traceparent)
    # _parse_traceparent yields both ids or neither, never one, so `and` and `or`
    # cannot be told apart by any input.
    both_parsed = trace_id is not None and span_id is not None  # pragma: no mutate
    traceparent = raw_traceparent if both_parsed else None
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

    Keys must be RFC 7230 tokens, as the W3C Baggage spec requires, and control
    characters are stripped from values. This is a security boundary, not
    pedantry: a baggage key becomes a log-attribute key, and the console renderer
    quotes values but not keys — so a newline in a key from an untrusted inbound
    header forges an entire additional log record. Rejecting non-token keys stops
    that where the hostile header is first parsed.
    """
    result: dict[str, str] = {}
    for member in raw.split(","):
        # Taking [0] makes maxsplit irrelevant: the text before the first ";" is
        # identical for every maxsplit >= 1.
        kv = member.split(";", 1)[0]  # pragma: no mutate
        if "=" not in kv:
            continue
        key, _, value = kv.partition("=")
        key = key.strip()
        if key and _BAGGAGE_TOKEN_RE.fullmatch(key):
            result[key] = _CONTROL_CHARS_RE.sub("", value.strip())
    return result


def _is_injectable_id(value: str | None, length: int) -> bool:
    """Validate a trace/span ID for outbound injection.

    W3C trace-context requires lowercase hex of the exact field width and
    rejects the all-zero value; anything else must not be emitted.
    """
    if value is None or len(value) != length:
        return False
    if value == "0" * length:
        return False
    return all(c in _HEX_DIGITS for c in value)


def inject_traceparent(headers: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """Write the current trace context into ``headers`` for an outbound call.

    Prefers the live OTel span context (full ``traceparent``/``tracestate``
    injection via the SDK propagator). Without OTel, falls back to the facade
    contextvars mirrored by ``@trace``/``span()`` and inbound extraction,
    emitting a version-00 ``traceparent`` with the sampled flag and forwarding
    any bound ``tracestate``. When no valid context is current, ``headers`` is
    returned unchanged. Returns the same mapping for call-site chaining::

        httpx.post(url, headers=inject_traceparent({"authorization": token}))
    """
    if inject_w3c_context(headers):
        return headers
    trace_id = get_trace_id()
    span_id = get_span_id()
    if not _is_injectable_id(trace_id, _TRACE_ID_LENGTH) or not _is_injectable_id(span_id, _SPAN_ID_LENGTH):
        return headers
    headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
    tracestate = get_context().get("tracestate")
    if isinstance(tracestate, str) and tracestate:
        headers["tracestate"] = tracestate
    return headers


def bind_propagation_context(context: PropagationContext) -> None:
    # NOTE: Total allocations on the bind/clear hot path are dominated by the
    # upstream `attach_w3c_context` → `TraceState.from_header` call (≈8 allocs
    # per header pair in OTel 1.41; previously ≈4 in 1.40). The memray
    # baseline bump in commit 5826e17 tracks that upstream change, not any
    # regression in this module.
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
        _OTEL_TOKEN_FIELD: otel_token,
        # Injected baggage.* keys split into two fields so the common
        # no-overlap case pays no extra allocations vs. the old list-only
        # snapshot. `_baggage_keys` is the unbind list; `_baggage_prior`
        # holds only keys that had a pre-existing value to restore (the
        # nested-same-key case from the clear_propagation_context fix).
        _BAGGAGE_KEYS_FIELD: (),
        _BAGGAGE_PRIOR_FIELD: {},
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
        keys: list[str] = []
        prior: dict[str, object] = {}
        for key, value in parse_baggage(context.baggage).items():
            ctx_key = f"baggage.{key}"
            prev = logger_ctx.get(ctx_key, _MISSING)
            if prev is not _MISSING:
                prior[ctx_key] = prev
            keys.append(ctx_key)
            bind_context(**{ctx_key: value})
        snapshot[_BAGGAGE_KEYS_FIELD] = tuple(keys)
        if prior:
            snapshot[_BAGGAGE_PRIOR_FIELD] = prior
    if context.trace_id is not None or context.span_id is not None:
        set_trace_context(context.trace_id, context.span_id)


def _narrow_id(value: object) -> str | None:
    """Narrow a snapshot id to ``str | None``.

    Type narrowing only: the snapshot always holds a str or None, so the guard
    and the else-branch resolve to the same value for every real input, making
    every mutation here equivalent. Kept as its own single-line return because
    mutmut only honours the pragma on a whole one-line statement.
    """
    return value if isinstance(value, str) or value is None else None  # pragma: no mutate


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
            _OTEL_TOKEN_FIELD: None,
        }
    # Detach only the OTel token introduced by this specific bind frame.
    detach_w3c_context(previous.get(_OTEL_TOKEN_FIELD))
    for key in ("traceparent", "tracestate", "baggage"):
        value = previous[key]
        if value is _MISSING:
            unbind_context(key)
        else:
            bind_context(**{key: value})
    # Unbind auto-injected baggage.* keys. When an outer frame already bound
    # the same baggage.* key, restore its value from `_baggage_prior` instead
    # of unbinding (fix from 7623d8d). Iterating the key tuple by index avoids
    # the per-iter tuple allocation that `.items()` pays on the hot path.
    raw_keys = previous.get(
        _BAGGAGE_KEYS_FIELD, ()
    )  # pragma: no mutate — empty-tuple default; for-loop below is a no-op when absent
    keys_seq: tuple[str, ...] = raw_keys if isinstance(raw_keys, tuple) else ()  # ty: ignore[invalid-assignment]
    raw_prior = previous.get(
        _BAGGAGE_PRIOR_FIELD, {}
    )  # pragma: no mutate — empty-dict default; membership check below is a no-op when absent
    prior_map: dict[str, object] = raw_prior if isinstance(raw_prior, dict) else {}  # ty: ignore[invalid-assignment]
    for bkey in keys_seq:
        if bkey in prior_map:
            bind_context(**{bkey: prior_map[bkey]})
        else:
            unbind_context(bkey)
    prev_trace_id = previous["trace_id"]
    prev_span_id = previous["span_id"]
    set_trace_context(_narrow_id(prev_trace_id), _narrow_id(prev_span_id))
