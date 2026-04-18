# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Edge-case tests for W3C trace context propagation."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from provide.telemetry import propagation as propagation_mod
from provide.telemetry.logger.context import clear_context, get_context
from provide.telemetry.propagation import (
    PropagationContext,
    _parse_traceparent,
    bind_propagation_context,
    clear_propagation_context,
    extract_w3c_context,
)
from provide.telemetry.tracing.context import get_trace_context, set_trace_context


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    clear_context()
    set_trace_context(None, None)


# ── _parse_traceparent: exhaustive edge cases ──────────────────────────


class TestParseTraceparentEdgeCases:
    def test_none_input(self) -> None:
        assert _parse_traceparent(None) == (None, None)

    def test_empty_string(self) -> None:
        assert _parse_traceparent("") == (None, None)

    def test_too_few_dashes(self) -> None:
        assert _parse_traceparent("00-abcd") == (None, None)

    def test_too_many_dashes(self) -> None:
        assert _parse_traceparent("00-" + "a" * 32 + "-" + "b" * 16 + "-01-extra") == (None, None)

    def test_version_ff_rejected(self) -> None:
        """W3C spec: version ff is reserved and must be rejected."""
        assert _parse_traceparent(f"ff-{'a' * 32}-{'b' * 16}-01") == (None, None)

    def test_version_ff_case_insensitive(self) -> None:
        assert _parse_traceparent(f"FF-{'a' * 32}-{'b' * 16}-01") == (None, None)
        assert _parse_traceparent(f"Ff-{'a' * 32}-{'b' * 16}-01") == (None, None)

    def test_version_00_accepted(self) -> None:
        tid, sid = _parse_traceparent(f"00-{'a' * 32}-{'b' * 16}-01")
        assert tid == "a" * 32
        assert sid == "b" * 16

    def test_version_01_accepted(self) -> None:
        """Non-zero, non-ff versions should be accepted (forward compat)."""
        tid, sid = _parse_traceparent(f"01-{'a' * 32}-{'b' * 16}-01")
        assert tid == "a" * 32
        assert sid == "b" * 16

    def test_version_fe_accepted(self) -> None:
        tid, sid = _parse_traceparent(f"fe-{'a' * 32}-{'b' * 16}-01")
        assert tid == "a" * 32
        assert sid == "b" * 16

    def test_trace_flags_00_accepted(self) -> None:
        tid, _sid = _parse_traceparent(f"00-{'a' * 32}-{'b' * 16}-00")
        assert tid == "a" * 32

    def test_trace_flags_ff_accepted(self) -> None:
        """Unlike version, trace_flags=ff is valid."""
        tid, _sid = _parse_traceparent(f"00-{'a' * 32}-{'b' * 16}-ff")
        assert tid == "a" * 32

    def test_uppercase_ids_normalized(self) -> None:
        tid, sid = _parse_traceparent(f"00-{'A' * 32}-{'B' * 16}-01")
        assert tid == "a" * 32
        assert sid == "b" * 16

    def test_mixed_case_ids_normalized(self) -> None:
        tid, sid = _parse_traceparent("00-aAbBcCdDeEfF0011aAbBcCdDeEfF0011-aAbBcCdDeEfF0011-01")
        assert tid == "aabbccddeeff0011aabbccddeeff0011"
        assert sid == "aabbccddeeff0011"

    def test_non_hex_in_middle_of_trace_id(self) -> None:
        bad = "a" * 15 + "g" + "a" * 16
        assert _parse_traceparent(f"00-{bad}-{'b' * 16}-01") == (None, None)

    def test_non_hex_in_middle_of_span_id(self) -> None:
        bad = "b" * 7 + "g" + "b" * 8
        assert _parse_traceparent(f"00-{'a' * 32}-{bad}-01") == (None, None)


# ── extract_w3c_context: deeper scenarios ──────────────────────────────


class TestExtractW3cContextEdgeCases:
    def test_missing_headers_key(self) -> None:
        scope: dict[str, Any] = {}
        ctx = extract_w3c_context(scope)
        assert ctx.traceparent is None
        assert ctx.tracestate is None
        assert ctx.baggage is None
        assert ctx.trace_id is None
        assert ctx.span_id is None

    def test_empty_headers_list(self) -> None:
        scope: dict[str, Any] = {"headers": []}
        ctx = extract_w3c_context(scope)
        assert ctx.traceparent is None

    def test_tracestate_without_traceparent(self) -> None:
        scope: dict[str, Any] = {"headers": [(b"tracestate", b"vendor=val")]}
        ctx = extract_w3c_context(scope)
        assert ctx.traceparent is None
        assert ctx.tracestate == "vendor=val"
        assert ctx.trace_id is None

    def test_all_three_headers_present(self) -> None:
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
                (b"tracestate", b"congo=lZWRzIHRoZQ"),
                (b"baggage", b"userId=alice"),
            ]
        }
        ctx = extract_w3c_context(scope)
        assert ctx.traceparent == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        assert ctx.tracestate == "congo=lZWRzIHRoZQ"
        assert ctx.baggage == "userId=alice"
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert ctx.span_id == "00f067aa0ba902b7"

    def test_invalid_traceparent_still_extracts_other_headers(self) -> None:
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"invalid-header-value"),
                (b"tracestate", b"vendor=val"),
                (b"baggage", b"key=val"),
            ]
        }
        ctx = extract_w3c_context(scope)
        assert ctx.traceparent is None
        assert ctx.trace_id is None
        assert ctx.tracestate == "vendor=val"
        assert ctx.baggage == "key=val"


# ── bind/clear lifecycle ───────────────────────────────────────────────


class TestBindClearLifecycle:
    def test_bind_sets_logger_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", MagicMock(return_value="tok"))
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda _t: None)

        ctx = PropagationContext(
            traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            tracestate="vendor=val",
            baggage="key=val",
            trace_id="a" * 32,
            span_id="b" * 16,
        )
        bind_propagation_context(ctx)

        logger_ctx = get_context()
        assert logger_ctx["traceparent"] == ctx.traceparent
        assert logger_ctx["tracestate"] == "vendor=val"
        assert logger_ctx["baggage"] == "key=val"

        trace_ctx = get_trace_context()
        assert trace_ctx["trace_id"] == "a" * 32
        assert trace_ctx["span_id"] == "b" * 16

    def test_clear_resets_trace_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", MagicMock(return_value="tok"))
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda _t: None)

        ctx = PropagationContext(
            traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            tracestate=None,
            baggage=None,
            trace_id="a" * 32,
            span_id="b" * 16,
        )
        bind_propagation_context(ctx)
        clear_propagation_context()

        assert get_trace_context() == {"trace_id": None, "span_id": None}
        assert get_context() == {}

    def test_clear_without_bind_is_safe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Calling clear without a prior bind should not crash."""
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda _t: None)
        propagation_mod._restore_stack.set(())
        clear_propagation_context()
        assert get_trace_context() == {"trace_id": None, "span_id": None}

    def test_bind_with_no_traceparent_skips_otel_attach(self, monkeypatch: pytest.MonkeyPatch) -> None:
        attach_calls: list[object] = []
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", lambda *a: attach_calls.append(a))

        ctx = PropagationContext(
            traceparent=None,
            tracestate="vendor=val",
            baggage=None,
            trace_id="a" * 32,
            span_id="b" * 16,
        )
        bind_propagation_context(ctx)
        assert len(attach_calls) == 0  # No attach since traceparent is None

    def test_nested_bind_clear_restores_outer_logger_and_trace_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", MagicMock(return_value="tok"))
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda _t: None)

        outer = PropagationContext(
            traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
            tracestate="outer=1",
            baggage="outer=yes",
            trace_id="a" * 32,
            span_id="b" * 16,
        )
        inner = PropagationContext(
            traceparent="00-" + "c" * 32 + "-" + "d" * 16 + "-01",
            tracestate="inner=1",
            baggage="inner=yes",
            trace_id="c" * 32,
            span_id="d" * 16,
        )
        bind_propagation_context(outer)
        outer_logger_ctx = get_context()
        outer_trace_ctx = get_trace_context()

        bind_propagation_context(inner)
        assert get_context()["traceparent"] == inner.traceparent
        assert get_trace_context()["trace_id"] == inner.trace_id

        clear_propagation_context()
        assert get_context() == outer_logger_ctx
        assert get_trace_context() == outer_trace_ctx

        clear_propagation_context()
        assert get_context() == {}
        assert get_trace_context() == {"trace_id": None, "span_id": None}

    def test_nested_same_baggage_key_restores_outer_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Regression: inner frame overwriting the same baggage.foo key as the outer
        # frame must restore the outer value on clear, not unbind it.
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", MagicMock(return_value=None))
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda _t: None)

        outer = PropagationContext(
            traceparent=None,
            tracestate=None,
            baggage="foo=outer",
            trace_id=None,
            span_id=None,
        )
        inner = PropagationContext(
            traceparent=None,
            tracestate=None,
            baggage="foo=inner",
            trace_id=None,
            span_id=None,
        )
        bind_propagation_context(outer)
        assert get_context()["baggage.foo"] == "outer"

        bind_propagation_context(inner)
        assert get_context()["baggage.foo"] == "inner"

        clear_propagation_context()
        # Outer value must be preserved, not unbound.
        assert get_context()["baggage.foo"] == "outer"
        assert get_context()["baggage"] == "foo=outer"

        clear_propagation_context()
        assert "baggage.foo" not in get_context()
        assert "baggage" not in get_context()


# ── Async context isolation ────────────────────────────────────────────


class TestPropagationAsyncIsolation:
    async def test_propagation_context_isolated_between_tasks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", MagicMock(return_value="tok"))
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda _t: None)

        results: dict[str, dict[str, str | None]] = {}

        async def task(name: str, tid: str) -> None:
            ctx = PropagationContext(
                traceparent=f"00-{tid}-{'b' * 16}-01",
                tracestate=None,
                baggage=None,
                trace_id=tid,
                span_id="b" * 16,
            )
            bind_propagation_context(ctx)
            await asyncio.sleep(0)  # yield
            results[name] = dict(get_trace_context())

        await asyncio.gather(
            task("task1", "1" * 32),
            task("task2", "2" * 32),
        )
        assert results["task1"]["trace_id"] == "1" * 32
        assert results["task2"]["trace_id"] == "2" * 32


# ── PropagationContext dataclass ───────────────────────────────────────


class TestPropagationContextDataclass:
    def test_frozen_immutable(self) -> None:
        ctx = PropagationContext(
            traceparent="tp",
            tracestate="ts",
            baggage="bg",
            trace_id="tid",
            span_id="sid",
        )
        with pytest.raises(AttributeError):
            ctx.trace_id = "new"  # type: ignore[misc]

    def test_equality(self) -> None:
        a = PropagationContext("tp", "ts", "bg", "tid", "sid")
        b = PropagationContext("tp", "ts", "bg", "tid", "sid")
        assert a == b

    def test_inequality(self) -> None:
        a = PropagationContext("tp", "ts", "bg", "tid1", "sid")
        b = PropagationContext("tp", "ts", "bg", "tid2", "sid")
        assert a != b

    def test_all_none(self) -> None:
        ctx = PropagationContext(None, None, None, None, None)
        assert ctx.traceparent is None
        assert ctx.trace_id is None


class TestParseBaggage:
    """Cover parse_baggage edge cases for 100% branch coverage."""

    def test_parses_simple_baggage(self) -> None:
        from provide.telemetry.propagation import parse_baggage

        result = parse_baggage("userId=alice,tenant=acme")
        assert result == {"userId": "alice", "tenant": "acme"}

    def test_strips_properties_after_semicolon(self) -> None:
        from provide.telemetry.propagation import parse_baggage

        result = parse_baggage("requestId=req-123;ttl=30")
        assert result == {"requestId": "req-123"}

    def test_skips_members_without_equals(self) -> None:
        from provide.telemetry.propagation import parse_baggage

        result = parse_baggage("good=val,badmember,also=ok")
        assert result == {"good": "val", "also": "ok"}

    def test_skips_empty_key(self) -> None:
        from provide.telemetry.propagation import parse_baggage

        result = parse_baggage("=nokey,real=val")
        assert result == {"real": "val"}

    def test_empty_string(self) -> None:
        from provide.telemetry.propagation import parse_baggage

        result = parse_baggage("")
        assert result == {}
