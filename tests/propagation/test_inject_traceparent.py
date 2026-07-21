# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests for outbound W3C trace-context injection (``inject_traceparent``)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from provide.telemetry import _otel
from provide.telemetry import propagation as propagation_mod
from provide.telemetry.logger.context import bind_context, clear_context
from provide.telemetry.propagation import inject_traceparent
from provide.telemetry.tracing.context import set_trace_context

_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
_SPAN_ID = "00f067aa0ba902b7"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_context()
    set_trace_context(None, None)
    # Default: behave as if OTel is unavailable so the contextvar fallback is
    # exercised deterministically regardless of the installed extras.
    monkeypatch.setattr(propagation_mod, "inject_w3c_context", lambda _carrier: False)


# ── contextvar fallback path ───────────────────────────────────────────


class TestInjectTraceparentFallback:
    def test_no_context_leaves_headers_unchanged(self) -> None:
        headers: dict[str, str] = {"authorization": "Bearer x"}
        result = inject_traceparent(headers)
        assert result == {"authorization": "Bearer x"}

    def test_returns_same_mapping_object(self) -> None:
        headers: dict[str, str] = {}
        assert inject_traceparent(headers) is headers

    def test_valid_context_writes_traceparent(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID)
        headers = inject_traceparent({})
        assert headers["traceparent"] == f"00-{_TRACE_ID}-{_SPAN_ID}-01"

    def test_existing_traceparent_is_overwritten(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID)
        headers = inject_traceparent({"traceparent": f"00-{'b' * 32}-{'c' * 16}-00"})
        assert headers["traceparent"] == f"00-{_TRACE_ID}-{_SPAN_ID}-01"

    def test_missing_trace_id_skips_injection(self) -> None:
        set_trace_context(None, _SPAN_ID)
        assert inject_traceparent({}) == {}

    def test_missing_span_id_skips_injection(self) -> None:
        set_trace_context(_TRACE_ID, None)
        assert inject_traceparent({}) == {}

    def test_short_trace_id_skips_injection(self) -> None:
        set_trace_context("a" * 31, _SPAN_ID)
        assert inject_traceparent({}) == {}

    def test_long_trace_id_skips_injection(self) -> None:
        set_trace_context("a" * 33, _SPAN_ID)
        assert inject_traceparent({}) == {}

    def test_short_span_id_skips_injection(self) -> None:
        set_trace_context(_TRACE_ID, "b" * 15)
        assert inject_traceparent({}) == {}

    def test_long_span_id_skips_injection(self) -> None:
        set_trace_context(_TRACE_ID, "b" * 17)
        assert inject_traceparent({}) == {}

    def test_all_zero_trace_id_skips_injection(self) -> None:
        set_trace_context("0" * 32, _SPAN_ID)
        assert inject_traceparent({}) == {}

    def test_all_zero_span_id_skips_injection(self) -> None:
        set_trace_context(_TRACE_ID, "0" * 16)
        assert inject_traceparent({}) == {}

    def test_non_hex_trace_id_skips_injection(self) -> None:
        set_trace_context("g" * 32, _SPAN_ID)
        assert inject_traceparent({}) == {}

    def test_non_hex_span_id_skips_injection(self) -> None:
        set_trace_context(_TRACE_ID, "z" * 16)
        assert inject_traceparent({}) == {}

    def test_uppercase_trace_id_skips_injection(self) -> None:
        """W3C requires lowercase hex; refuse to emit an invalid header."""
        set_trace_context(_TRACE_ID.upper(), _SPAN_ID)
        assert inject_traceparent({}) == {}

    def test_uppercase_span_id_skips_injection(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID.upper())
        assert inject_traceparent({}) == {}

    def test_preserves_unrelated_headers(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID)
        headers = inject_traceparent({"x-request-id": "r1"})
        assert headers["x-request-id"] == "r1"
        assert "traceparent" in headers


# ── tracestate forwarding (fallback path) ──────────────────────────────


class TestInjectTracestateForwarding:
    def test_bound_tracestate_is_forwarded(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID)
        bind_context(tracestate="vendor=value")
        headers = inject_traceparent({})
        assert headers["tracestate"] == "vendor=value"

    def test_absent_tracestate_not_written(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID)
        headers = inject_traceparent({})
        assert "tracestate" not in headers

    def test_empty_tracestate_not_written(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID)
        bind_context(tracestate="")
        headers = inject_traceparent({})
        assert "tracestate" not in headers

    def test_non_string_tracestate_not_written(self) -> None:
        set_trace_context(_TRACE_ID, _SPAN_ID)
        bind_context(tracestate=42)
        headers = inject_traceparent({})
        assert "tracestate" not in headers

    def test_no_traceparent_means_no_tracestate(self) -> None:
        """tracestate must never be emitted without a traceparent."""
        bind_context(tracestate="vendor=value")
        headers = inject_traceparent({})
        assert headers == {}


# ── OTel-preferred path ────────────────────────────────────────────────


class TestInjectTraceparentOtelPath:
    def test_otel_injection_wins_over_contextvars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        otel_header = f"00-{'d' * 32}-{'e' * 16}-01"

        def _fake_inject(carrier: dict[str, str]) -> bool:
            carrier["traceparent"] = otel_header
            return True

        monkeypatch.setattr(propagation_mod, "inject_w3c_context", _fake_inject)
        set_trace_context(_TRACE_ID, _SPAN_ID)
        headers = inject_traceparent({})
        assert headers["traceparent"] == otel_header

    def test_otel_false_falls_back_to_contextvars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(propagation_mod, "inject_w3c_context", lambda _carrier: False)
        set_trace_context(_TRACE_ID, _SPAN_ID)
        headers = inject_traceparent({})
        assert headers["traceparent"] == f"00-{_TRACE_ID}-{_SPAN_ID}-01"

    def test_otel_path_returns_same_mapping_object(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(propagation_mod, "inject_w3c_context", lambda _carrier: True)
        headers: dict[str, str] = {}
        assert inject_traceparent(headers) is headers


# ── _otel.inject_w3c_context ───────────────────────────────────────────


class TestInjectW3CContext:
    def test_import_error_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(_otel, "_import_module", lambda _: (_ for _ in ()).throw(ImportError()))
        carrier: dict[str, str] = {}
        assert _otel.inject_w3c_context(carrier) is False
        assert carrier == {}

    def test_propagator_writes_traceparent_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[dict[str, str]] = []

        class _FakePropagator:
            def inject(self, carrier: dict[str, str]) -> None:
                seen.append(carrier)
                carrier["traceparent"] = f"00-{'a' * 32}-{'b' * 16}-01"

        modules = {
            "opentelemetry.trace.propagation.tracecontext": SimpleNamespace(
                TraceContextTextMapPropagator=_FakePropagator
            ),
        }
        monkeypatch.setattr(_otel, "_import_module", lambda name: modules[name])
        carrier: dict[str, str] = {}
        assert _otel.inject_w3c_context(carrier) is True
        assert seen == [carrier]

    def test_propagator_writes_nothing_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _NoopPropagator:
            def inject(self, carrier: dict[str, str]) -> None:
                return None

        modules = {
            "opentelemetry.trace.propagation.tracecontext": SimpleNamespace(
                TraceContextTextMapPropagator=_NoopPropagator
            ),
        }
        monkeypatch.setattr(_otel, "_import_module", lambda name: modules[name])
        assert _otel.inject_w3c_context({}) is False


# ── public API export ──────────────────────────────────────────────────


def test_inject_traceparent_is_exported() -> None:
    import provide.telemetry as t

    assert callable(t.inject_traceparent)
    assert "inject_traceparent" in t.__all__


# ── real OTel round-trip ───────────────────────────────────────────────


@pytest.mark.otel
def test_inject_matches_live_otel_span(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("opentelemetry.sdk.trace")
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider

    monkeypatch.undo()  # restore the real inject_w3c_context
    provider = TracerProvider()
    tracer: Any = provider.get_tracer("inject-test")
    with tracer.start_as_current_span("outbound") as sp:
        headers = inject_traceparent({})
        ctx = sp.get_span_context()
        expected_trace_id = otel_trace.format_trace_id(ctx.trace_id)
        expected_span_id = otel_trace.format_span_id(ctx.span_id)
        version, trace_id, span_id, flags = headers["traceparent"].split("-")
        assert version == "00"
        assert trace_id == expected_trace_id
        assert span_id == expected_span_id
        assert int(flags, 16) & 0x01  # sampled bit set
