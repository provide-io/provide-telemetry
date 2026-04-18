# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Tests targeting mutation-testing survivors in propagation.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from provide.telemetry import propagation as propagation_mod
from provide.telemetry.logger import context as logger_context_mod
from provide.telemetry.logger.context import clear_context
from provide.telemetry.tracing import context as tracing_context_mod
from provide.telemetry.tracing.context import set_trace_context


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    clear_context()
    set_trace_context(None, None)


# ---------------------------------------------------------------------------
# _parse_traceparent survivors
# ---------------------------------------------------------------------------


class TestParseTraceparent:
    """Kill mutants in _parse_traceparent validation logic."""

    def test_all_zero_trace_id_valid_span_id_returns_none(self) -> None:
        """Kills `or` -> `and` mutant on zero-id check.

        If trace_id is all zeros but span_id is valid, result must be None.
        The `and` mutant would require BOTH to be zero, so this would slip through.
        """
        result = propagation_mod._parse_traceparent("00-00000000000000000000000000000000-00f067aa0ba902b7-01")
        assert result == (None, None)

    def test_all_zero_span_id_valid_trace_id_returns_none(self) -> None:
        """Kills `or` -> `and` mutant from the other direction."""
        result = propagation_mod._parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01")
        assert result == (None, None)

    def test_both_ids_zero_returns_none(self) -> None:
        """Baseline: both zero IDs also rejected."""
        result = propagation_mod._parse_traceparent("00-00000000000000000000000000000000-0000000000000000-01")
        assert result == (None, None)

    def test_wrong_version_length_returns_none(self) -> None:
        """Kills `or` -> `and` on length validation chain.

        Only version length is wrong; others are correct.
        """
        result = propagation_mod._parse_traceparent("0-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        assert result == (None, None)

    def test_wrong_trace_id_length_only(self) -> None:
        """Only trace_id length is wrong."""
        result = propagation_mod._parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e473-00f067aa0ba902b7-01")
        assert result == (None, None)

    def test_wrong_span_id_length_only(self) -> None:
        """Only span_id length is wrong."""
        result = propagation_mod._parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b-01")
        assert result == (None, None)

    def test_wrong_flags_length_only(self) -> None:
        """Only trace_flags length is wrong."""
        result = propagation_mod._parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-0")
        assert result == (None, None)

    def test_non_hex_version_returns_none(self) -> None:
        """Kills int(version, 16) arg mutations (int(16), int(version,), int(version, 17))."""
        result = propagation_mod._parse_traceparent("zz-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        assert result == (None, None)

    def test_non_hex_trace_id_returns_none(self) -> None:
        """Kills int(trace_id, 16) arg mutations."""
        result = propagation_mod._parse_traceparent("00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-00f067aa0ba902b7-01")
        assert result == (None, None)

    def test_non_hex_span_id_returns_none(self) -> None:
        """Kills int(span_id, 16) arg mutations."""
        result = propagation_mod._parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-zzzzzzzzzzzzzzzz-01")
        assert result == (None, None)

    def test_non_hex_trace_flags_returns_none(self) -> None:
        """Kills int(trace_flags, 16) arg mutations."""
        result = propagation_mod._parse_traceparent("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-zz")
        assert result == (None, None)

    def test_valid_traceparent_returns_ids(self) -> None:
        """Baseline: valid traceparent returns correct trace_id and span_id."""
        trace_id, span_id = propagation_mod._parse_traceparent(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )
        assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert span_id == "00f067aa0ba902b7"

    def test_string_literal_zero_mutation(self) -> None:
        """Kills string literal mutations on "0".

        Uses a trace_id that is NOT all zeros but contains many zeros,
        ensuring the "0" * 32 comparison is exact.
        """
        trace_id, span_id = propagation_mod._parse_traceparent(
            "00-00000000000000000000000000000001-00f067aa0ba902b7-01"
        )
        assert trace_id == "00000000000000000000000000000001"
        assert span_id == "00f067aa0ba902b7"

    def test_span_id_not_all_zeros_but_close(self) -> None:
        """Ensures span_id exactly "0"*16 is rejected but "0"*15 + "1" is not."""
        trace_id, span_id = propagation_mod._parse_traceparent(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000001-01"
        )
        assert trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert span_id == "0000000000000001"


# ---------------------------------------------------------------------------
# extract_w3c_context survivors
# ---------------------------------------------------------------------------


class TestExtractW3cContext:
    """Kill mutants in extract_w3c_context."""

    def test_baggage_header_populates_field(self) -> None:
        """Kills `baggage = None` and wrong-header-name mutants."""
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
                (b"baggage", b"key1=val1,key2=val2"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.baggage == "key1=val1,key2=val2"

    def test_no_baggage_header_gives_none(self) -> None:
        """Baseline: missing baggage header yields None."""
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.baggage is None

    def test_invalid_traceparent_nullifies_traceparent_field(self) -> None:
        """Kills `and` -> `or` mutant in traceparent validation.

        When parse returns (None, None), traceparent field must be None.
        """
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"invalid"),
                (b"tracestate", b"vendor=val"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.traceparent is None
        # tracestate is still extracted raw
        assert ctx.tracestate == "vendor=val"

    def test_valid_traceparent_preserves_raw_value(self) -> None:
        """Ensures traceparent field equals raw header when parse succeeds."""
        raw = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        scope: dict[str, Any] = {"headers": [(b"traceparent", raw.encode())]}
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.traceparent == raw

    def test_baggage_passed_to_return_value(self) -> None:
        """Kills baggage=None mutant in PropagationContext constructor."""
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
                (b"baggage", b"foo=bar"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.baggage == "foo=bar"
        assert ctx.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"


# ---------------------------------------------------------------------------
# bind_propagation_context survivors
# ---------------------------------------------------------------------------


class TestBindPropagationContext:
    """Kill mutants in bind_propagation_context."""

    def test_attach_called_with_correct_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills mutants that set attach args to None."""
        mock_attach = MagicMock(return_value="token")
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", mock_attach)
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", lambda t: None)

        ctx = propagation_mod.PropagationContext(
            traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            tracestate="vendor=val",
            baggage=None,
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
        )
        propagation_mod.bind_propagation_context(ctx)
        mock_attach.assert_called_once_with(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "vendor=val",
        )

    def test_baggage_binds_to_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `baggage is not None` -> `is None` mutant."""
        mock_attach = MagicMock(return_value="token")
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", mock_attach)

        bind_calls: list[dict[str, Any]] = []
        original_bind = logger_context_mod.bind_context

        def _tracking_bind(**kwargs: Any) -> None:
            bind_calls.append(kwargs)
            original_bind(**kwargs)

        monkeypatch.setattr("provide.telemetry.propagation.bind_context", _tracking_bind)

        ctx = propagation_mod.PropagationContext(
            traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            tracestate=None,
            baggage="key=val",
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
        )
        propagation_mod.bind_propagation_context(ctx)

        # Verify baggage was bound
        baggage_binds = [c for c in bind_calls if "baggage" in c]
        assert len(baggage_binds) == 1
        assert baggage_binds[0]["baggage"] == "key=val"

    def test_no_baggage_does_not_bind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `is not None` -> `is None` by checking None baggage doesn't bind."""
        mock_attach = MagicMock(return_value="token")
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", mock_attach)

        bind_calls: list[dict[str, Any]] = []
        original_bind = logger_context_mod.bind_context

        def _tracking_bind(**kwargs: Any) -> None:
            bind_calls.append(kwargs)
            original_bind(**kwargs)

        monkeypatch.setattr("provide.telemetry.propagation.bind_context", _tracking_bind)

        ctx = propagation_mod.PropagationContext(
            traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            tracestate=None,
            baggage=None,
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id="00f067aa0ba902b7",
        )
        propagation_mod.bind_propagation_context(ctx)

        baggage_binds = [c for c in bind_calls if "baggage" in c]
        assert len(baggage_binds) == 0

    def test_only_trace_id_set_calls_set_trace_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kills `or` -> `and` in trace_id/span_id check.

        When only trace_id is set (span_id is None), set_trace_context must
        still be called. The `and` mutant would skip this.
        """
        mock_attach = MagicMock(return_value="token")
        monkeypatch.setattr(propagation_mod, "attach_w3c_context", mock_attach)

        trace_calls: list[tuple[str | None, str | None]] = []
        original_set = tracing_context_mod.set_trace_context

        def _tracking_set(tid: str | None, sid: str | None) -> None:
            trace_calls.append((tid, sid))
            original_set(tid, sid)

        monkeypatch.setattr("provide.telemetry.propagation.set_trace_context", _tracking_set)

        ctx = propagation_mod.PropagationContext(
            traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            tracestate=None,
            baggage=None,
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            span_id=None,
        )
        propagation_mod.bind_propagation_context(ctx)

        assert len(trace_calls) == 1
        assert trace_calls[0] == ("4bf92f3577b34da6a3ce929d0e0e4736", None)

    def test_only_span_id_set_calls_set_trace_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Symmetric case: only span_id set, trace_id is None."""
        trace_calls: list[tuple[str | None, str | None]] = []
        original_set = tracing_context_mod.set_trace_context

        def _tracking_set(tid: str | None, sid: str | None) -> None:
            trace_calls.append((tid, sid))
            original_set(tid, sid)

        monkeypatch.setattr("provide.telemetry.propagation.set_trace_context", _tracking_set)

        ctx = propagation_mod.PropagationContext(
            traceparent=None,
            tracestate=None,
            baggage=None,
            trace_id=None,
            span_id="00f067aa0ba902b7",
        )
        propagation_mod.bind_propagation_context(ctx)

        assert len(trace_calls) == 1
        assert trace_calls[0] == (None, "00f067aa0ba902b7")

    def test_neither_id_set_skips_set_trace_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both trace_id and span_id are None, set_trace_context is NOT called."""
        trace_calls: list[tuple[str | None, str | None]] = []

        def _tracking_set(tid: str | None, sid: str | None) -> None:
            trace_calls.append((tid, sid))

        monkeypatch.setattr("provide.telemetry.propagation.set_trace_context", _tracking_set)

        ctx = propagation_mod.PropagationContext(
            traceparent=None,
            tracestate=None,
            baggage=None,
            trace_id=None,
            span_id=None,
        )
        propagation_mod.bind_propagation_context(ctx)

        assert len(trace_calls) == 0

    def test_nested_bind_clear_restores_outer_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each bind frame owns its OTel token; clear detaches only that frame's token."""
        attach_calls: list[str] = []
        detach_calls: list[object] = []

        def fake_attach(traceparent: str | None, tracestate: str | None) -> str:
            token = f"token-{len(attach_calls)}"
            attach_calls.append(token)
            return token

        def fake_detach(token: object) -> None:
            detach_calls.append(token)

        monkeypatch.setattr(propagation_mod, "attach_w3c_context", fake_attach)
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", fake_detach)

        outer_ctx = propagation_mod.PropagationContext(
            traceparent="00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
            tracestate=None,
            baggage=None,
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            span_id="bbbbbbbbbbbbbbbb",
        )
        propagation_mod.bind_propagation_context(outer_ctx)
        assert len(attach_calls) == 1  # outer token attached

        inner_ctx = propagation_mod.PropagationContext(
            traceparent="00-cccccccccccccccccccccccccccccccc-dddddddddddddddd-01",
            tracestate=None,
            baggage=None,
            trace_id="cccccccccccccccccccccccccccccccc",
            span_id="dddddddddddddddd",
        )
        propagation_mod.bind_propagation_context(inner_ctx)
        assert len(attach_calls) == 2  # inner token attached

        propagation_mod.clear_propagation_context()
        # Inner clear detaches only the inner frame's token.
        assert detach_calls[-1] == "token-1"
        assert len(detach_calls) == 1  # outer not yet detached

        propagation_mod.clear_propagation_context()
        assert detach_calls[-1] == "token-0"  # type: ignore[comparison-overlap]
        assert len(detach_calls) == 2

    def test_inner_bind_without_traceparent_does_not_detach_outer_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Clearing an inner bind that had no traceparent must not detach the outer token."""
        attach_calls: list[str] = []
        detach_calls: list[object] = []

        def fake_attach(traceparent: str | None, tracestate: str | None) -> str:
            token = f"token-{len(attach_calls)}"
            attach_calls.append(token)
            return token

        def fake_detach(token: object) -> None:
            detach_calls.append(token)

        monkeypatch.setattr(propagation_mod, "attach_w3c_context", fake_attach)
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", fake_detach)

        outer_ctx = propagation_mod.PropagationContext(
            traceparent="00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
            tracestate="vendor=outer",
            baggage=None,
            trace_id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            span_id="bbbbbbbbbbbbbbbb",
        )
        inner_ctx = propagation_mod.PropagationContext(
            traceparent=None,  # no OTel attach for this frame
            tracestate="vendor=inner",
            baggage=None,
            trace_id=None,
            span_id=None,
        )

        propagation_mod.bind_propagation_context(outer_ctx)
        assert len(attach_calls) == 1

        propagation_mod.bind_propagation_context(inner_ctx)
        assert len(attach_calls) == 1  # no second attach

        propagation_mod.clear_propagation_context()
        # Inner frame had no token — detach should be called with None (no-op in real OTel).
        assert detach_calls[-1] is None
        assert len(detach_calls) == 1

        # Outer token must still be intact — clearing inner did not detach it.
        propagation_mod.clear_propagation_context()
        assert detach_calls[-1] == "token-0"
        assert len(detach_calls) == 2

    def test_three_nested_clears_in_reverse_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kill mutant: stack[:-1] → stack[:+1].

        stack[:1] and stack[:-1] are equal for 2-element stacks, so we need 3
        levels of nesting where they diverge.  With stack[:+1], the middle
        snapshot is lost and the second clear restores the wrong token.
        """
        attach_calls: list[str] = []
        detach_calls: list[object] = []

        def fake_attach(traceparent: str | None, tracestate: str | None) -> str:
            token = f"token-{len(attach_calls)}"
            attach_calls.append(token)
            return token

        def fake_detach(token: object) -> None:
            detach_calls.append(token)

        monkeypatch.setattr(propagation_mod, "attach_w3c_context", fake_attach)
        monkeypatch.setattr(propagation_mod, "detach_w3c_context", fake_detach)

        for tp in [
            "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
            "00-cccccccccccccccccccccccccccccccc-dddddddddddddddd-01",
            "00-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee-ffffffffffffffff-01",
        ]:
            propagation_mod.bind_propagation_context(
                propagation_mod.PropagationContext(
                    traceparent=tp,
                    tracestate=None,
                    baggage=None,
                    trace_id=tp[3:35],
                    span_id=tp[36:52],
                )
            )
        assert attach_calls == ["token-0", "token-1", "token-2"]

        # Clear three times — tokens must detach in exact reverse order.
        propagation_mod.clear_propagation_context()
        assert detach_calls == ["token-2"]
        propagation_mod.clear_propagation_context()
        assert detach_calls == ["token-2", "token-1"]  # mutant yields token-0 here
        propagation_mod.clear_propagation_context()
        assert detach_calls == ["token-2", "token-1", "token-0"]


class TestExtractW3cContextSizeGuards:
    def test_tracestate_512_accepted(self) -> None:
        ts = "v" * 512
        scope: dict[str, Any] = {"headers": [(b"tracestate", ts.encode())]}
        assert propagation_mod.extract_w3c_context(scope).tracestate == ts

    def test_tracestate_32_pairs_accepted(self) -> None:
        ts = ",".join(f"v{i}=x" for i in range(32))
        scope: dict[str, Any] = {"headers": [(b"tracestate", ts.encode())]}
        assert propagation_mod.extract_w3c_context(scope).tracestate == ts

    def test_baggage_8192_accepted(self) -> None:
        bg = "k=" + "v" * 8190
        scope: dict[str, Any] = {"headers": [(b"baggage", bg.encode())]}
        assert propagation_mod.extract_w3c_context(scope).baggage == bg
