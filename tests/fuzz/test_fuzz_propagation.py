# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Fuzz the propagation surface — the only input that arrives from the network.

Every other input to this library comes from the operator (env vars, config
objects) or the developer (log calls). W3C headers arrive from whoever made the
HTTP request, so these parsers are the attack surface, and the invariants below
are the ones an attacker must not be able to break:

* nothing raises, whatever the bytes;
* a parsed trace/span id is always well-formed hex of the right length, so a
  malformed inbound header can never poison an outbound one;
* baggage keys are always RFC 7230 tokens and values never carry control
  characters, so a key can never forge a log record.

Mirrors go/fuzz_test.go, rust/tests/fuzz_test.rs and typescript/tests/fuzz/.
"""

from __future__ import annotations

from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from provide.telemetry.propagation import extract_w3c_context, parse_baggage

_HEX = "0123456789abcdef"
_TOKEN_CHARS = set("!#$%&'*+-.^_`|~0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _scope(**headers: str) -> dict[str, Any]:
    return {"type": "http", "headers": [(k.encode(), v.encode()) for k, v in headers.items()]}


@given(st.text(max_size=2048))
@settings(max_examples=400, deadline=None)
def test_parse_baggage_never_raises(raw: str) -> None:
    parse_baggage(raw)


@given(st.text(max_size=2048))
@settings(max_examples=400, deadline=None)
def test_parse_baggage_keys_are_always_tokens(raw: str) -> None:
    """A key that is not a token could forge a log record downstream."""
    for key in parse_baggage(raw):
        assert key, "empty keys must be dropped"
        assert set(key) <= _TOKEN_CHARS, f"non-token key survived: {key!r}"


@given(st.text(max_size=2048))
@settings(max_examples=400, deadline=None)
def test_parse_baggage_values_never_carry_controls(raw: str) -> None:
    for value in parse_baggage(raw).values():
        assert all(c == "\t" or not (ord(c) < 0x20 or ord(c) == 0x7F) for c in value), (
            f"control character survived in value: {value!r}"
        )


@given(st.text(max_size=1024), st.text(max_size=1024), st.text(max_size=1024))
@settings(max_examples=400, deadline=None)
def test_extract_w3c_context_never_raises(tp: str, ts: str, bg: str) -> None:
    extract_w3c_context(_scope(traceparent=tp, tracestate=ts, baggage=bg))


@given(st.text(max_size=1024))
@settings(max_examples=400, deadline=None)
def test_parsed_ids_are_always_well_formed(tp: str) -> None:
    """A malformed inbound header must never yield an id we would propagate."""
    ctx = extract_w3c_context(_scope(traceparent=tp))

    if ctx.trace_id is not None:
        assert len(ctx.trace_id) == 32
        assert set(ctx.trace_id) <= set(_HEX)
        assert ctx.trace_id != "0" * 32
    if ctx.span_id is not None:
        assert len(ctx.span_id) == 16
        assert set(ctx.span_id) <= set(_HEX)
        assert ctx.span_id != "0" * 16
    # The pair is all-or-nothing; a half-parsed header must not be forwarded.
    assert (ctx.trace_id is None) == (ctx.span_id is None)
    if ctx.trace_id is None:
        assert ctx.traceparent is None


@given(
    st.text(alphabet=_HEX, min_size=32, max_size=32),
    st.text(alphabet=_HEX, min_size=16, max_size=16),
)
@settings(max_examples=200, deadline=None)
def test_well_formed_traceparents_round_trip(trace_id: str, span_id: str) -> None:
    assume(trace_id != "0" * 32 and span_id != "0" * 16)
    header = f"00-{trace_id}-{span_id}-01"

    ctx = extract_w3c_context(_scope(traceparent=header))

    assert ctx.trace_id == trace_id
    assert ctx.span_id == span_id
    assert ctx.traceparent == header
