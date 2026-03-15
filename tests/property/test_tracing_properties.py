# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Property-based tests for tracing context, NoopSpan, and resilience."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from undef.telemetry.resilience import (
    ExporterPolicy,
    get_exporter_policy,
    reset_resilience_for_tests,
    set_exporter_policy,
)
from undef.telemetry.tracing.context import get_trace_context, set_trace_context
from undef.telemetry.tracing.provider import _NoopSpan, _NoopTracer

# ── Trace context properties ──────────────────────────────────────────


@given(
    trace_id=st.one_of(st.none(), st.text(min_size=1, max_size=32)),
    span_id=st.one_of(st.none(), st.text(min_size=1, max_size=16)),
)
@settings(max_examples=50)
def test_set_get_trace_context_roundtrip(trace_id: str | None, span_id: str | None) -> None:
    set_trace_context(trace_id, span_id)
    ctx = get_trace_context()
    assert ctx["trace_id"] == trace_id
    assert ctx["span_id"] == span_id
    set_trace_context(None, None)


@given(name=st.text(min_size=0, max_size=64))
@settings(max_examples=30)
def test_noop_span_preserves_name(name: str) -> None:
    span = _NoopSpan(name)
    assert span.name == name


@given(name=st.text(min_size=1, max_size=32))
@settings(max_examples=30)
def test_noop_span_context_lifecycle(name: str) -> None:
    span = _NoopSpan(name)
    with span:
        ctx = get_trace_context()
        assert ctx["trace_id"] == "0" * 32
        assert ctx["span_id"] == "0" * 16
    ctx = get_trace_context()
    assert ctx["trace_id"] is None
    assert ctx["span_id"] is None


@given(name=st.text(min_size=1, max_size=32))
@settings(max_examples=30)
def test_noop_tracer_always_returns_noop_span(name: str) -> None:
    tracer = _NoopTracer()
    span = tracer.start_as_current_span(name)
    assert isinstance(span, _NoopSpan)
    assert span.name == name


# ── Resilience policy properties ──────────────────────────────────────


@given(
    signal=st.sampled_from(["logs", "traces", "metrics"]),
    retries=st.integers(min_value=0, max_value=10),
    backoff=st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
    timeout=st.floats(min_value=0.0, max_value=30.0, allow_nan=False, allow_infinity=False),
    fail_open=st.booleans(),
)
@settings(max_examples=50)
def test_set_get_exporter_policy_roundtrip(
    signal: str, retries: int, backoff: float, timeout: float, fail_open: bool
) -> None:
    reset_resilience_for_tests()
    policy = ExporterPolicy(retries=retries, backoff_seconds=backoff, timeout_seconds=timeout, fail_open=fail_open)
    set_exporter_policy(signal, policy)
    result = get_exporter_policy(signal)
    assert result.retries == retries
    assert abs(result.backoff_seconds - backoff) < 1e-9
    assert abs(result.timeout_seconds - timeout) < 1e-9
    assert result.fail_open == fail_open
    reset_resilience_for_tests()
