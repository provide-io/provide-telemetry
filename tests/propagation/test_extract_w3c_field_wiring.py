# SPDX-FileCopyrightText: Copyright (C) 2026 MindTenet LLC
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of Undef Telemetry.
#

"""Tests targeting extract_w3c_context field-wiring mutants (23, 24, 26, 32, 33)."""

from __future__ import annotations

from typing import Any

from undef.telemetry import propagation as propagation_mod


class TestExtractW3cContextFieldWiring:
    """Kill mutants that replace args/return-fields with None in extract_w3c_context."""

    def test_raw_traceparent_forwarded_to_parse(self) -> None:
        """Kills mutmut_23: _parse_traceparent(raw_traceparent) -> _parse_traceparent(None).

        With a valid traceparent header, trace_id/span_id must be populated.
        Passing None would yield (None, None).
        """
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-abcdef1234567890abcdef1234567890-1234567890abcdef-01"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.trace_id == "abcdef1234567890abcdef1234567890"
        assert ctx.span_id == "1234567890abcdef"

    def test_traceparent_field_not_none_on_valid_parse(self) -> None:
        """Kills mutmut_24: traceparent=traceparent -> traceparent=None.

        When parse succeeds, the PropagationContext.traceparent must contain the raw header.
        """
        raw = "00-abcdef1234567890abcdef1234567890-1234567890abcdef-01"
        scope: dict[str, Any] = {"headers": [(b"traceparent", raw.encode())]}
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.traceparent is not None
        assert ctx.traceparent == raw

    def test_baggage_field_populated_from_header(self) -> None:
        """Kills mutmut_26: baggage=baggage -> baggage=None.

        When baggage header is present, PropagationContext.baggage must not be None.
        """
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-abcdef1234567890abcdef1234567890-1234567890abcdef-01"),
                (b"baggage", b"userId=alice"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.baggage is not None
        assert ctx.baggage == "userId=alice"

    def test_trace_id_field_in_return(self) -> None:
        """Kills mutmut_32: removes trace_id=trace_id from return.

        Without trace_id kwarg, PropagationContext defaults to None.
        """
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-abcdef1234567890abcdef1234567890-1234567890abcdef-01"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.trace_id is not None
        assert ctx.trace_id == "abcdef1234567890abcdef1234567890"

    def test_span_id_field_in_return(self) -> None:
        """Kills mutmut_33: removes span_id=span_id from return.

        Without span_id kwarg, PropagationContext defaults to None.
        """
        scope: dict[str, Any] = {
            "headers": [
                (b"traceparent", b"00-abcdef1234567890abcdef1234567890-1234567890abcdef-01"),
            ]
        }
        ctx = propagation_mod.extract_w3c_context(scope)
        assert ctx.span_id is not None
        assert ctx.span_id == "1234567890abcdef"
