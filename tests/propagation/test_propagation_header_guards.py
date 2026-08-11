# SPDX-FileCopyrightText: Copyright (C) 2026 provide.io llc
# SPDX-License-Identifier: Apache-2.0
# SPDX-Comment: Part of provide-telemetry.
#

"""Inbound-header guards: accepted sizes, and what baggage parsing strips.

Split out of ``test_propagation_mutations.py`` to keep both modules inside the
500-line ceiling ``scripts/check_max_loc.py`` enforces.
"""

from __future__ import annotations

from typing import Any

from provide.telemetry import propagation as propagation_mod


class TestExtractW3cContextSizeGuards:
    def test_tracestate_512_accepted(self) -> None:
        ts = "v=" + "x" * 510
        assert len(ts) == 512
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


class TestExtractW3cContextTracestateGrammar:
    """Malformed tracestate is dropped at extraction, before it can be bound.

    This is a security boundary: the bound value is later forwarded verbatim
    into an outbound HTTP header by ``inject_traceparent``'s fallback path, so
    a control character surviving here becomes header injection downstream.
    """

    @staticmethod
    def _extract(ts: str) -> str | None:
        scope: dict[str, Any] = {"headers": [(b"tracestate", ts.encode())]}
        return propagation_mod.extract_w3c_context(scope).tracestate

    def test_crlf_bearing_tracestate_dropped(self) -> None:
        assert self._extract("vendor=value\r\nx-injected: yes") is None

    def test_escape_bearing_tracestate_dropped(self) -> None:
        assert self._extract("vendor=va\x1b[31mlue") is None

    def test_member_without_equals_dropped(self) -> None:
        assert self._extract("vendorvalue") is None

    def test_second_invalid_member_drops_the_whole_header(self) -> None:
        assert self._extract("vendor=ok,bad\r\nmember=x") is None

    def test_valid_multi_member_kept(self) -> None:
        ts = "congo=t61rcWkgMzE,rojo=00f067aa0ba902b7"
        assert self._extract(ts) == ts

    def test_ows_after_comma_kept(self) -> None:
        ts = "congo=t61, rojo=00f"
        assert self._extract(ts) == ts

    def test_tab_ows_kept(self) -> None:
        ts = "congo=t61,\trojo=00f"
        assert self._extract(ts) == ts

    def test_multi_tenant_key_kept(self) -> None:
        ts = "az3@rojo=00f067aa"
        assert self._extract(ts) == ts

    def test_empty_value_member_kept(self) -> None:
        # W3C allows an empty value (0*255 is zero-or-more).
        assert self._extract("vendor=") == "vendor="

    def test_key_at_256_chars_kept(self) -> None:
        ts = "a" * 256 + "=x"
        assert self._extract(ts) == ts

    def test_key_at_257_chars_dropped(self) -> None:
        assert self._extract("a" * 257 + "=x") is None

    def test_uppercase_key_dropped(self) -> None:
        assert self._extract("Vendor=x") is None

    def test_comma_only_header_dropped(self) -> None:
        assert self._extract(",") is None


class TestParseBaggageControlStripping:
    """Control characters are *removed* from a baggage value, not replaced.

    The substitution is a security boundary — a baggage value becomes a log
    attribute, and the console renderer emits it into a line-oriented stream.
    Substituting anything other than the empty string would leave a marker in
    the operator's record and change the value the next hop propagates.
    """

    def test_control_characters_are_removed_leaving_nothing_behind(self) -> None:
        assert propagation_mod.parse_baggage("a=x\x00y") == {"a": "xy"}
        assert propagation_mod.parse_baggage("a=x\x1fy") == {"a": "xy"}
        assert propagation_mod.parse_baggage("a=x\x7fy") == {"a": "xy"}

    def test_a_value_that_is_only_control_characters_becomes_empty(self) -> None:
        assert propagation_mod.parse_baggage("a=\x00\x01\x02") == {"a": ""}

    def test_tab_survives(self) -> None:
        assert propagation_mod.parse_baggage("a=x\ty") == {"a": "x\ty"}
